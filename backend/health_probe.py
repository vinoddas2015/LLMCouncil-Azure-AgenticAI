"""
Health Probe Agent — Autonomous Backend Health Monitoring.

Monitors the LLM Council backend health and provides:
1. Deep health checks (beyond /health ping): DB, API connectivity, memory store
2. Self-healing: detects crash loops and reports diagnostics
3. Historical health tracking for trend analysis
4. Startup validation: ensures all critical subsystems are operational

Used by:
- The /api/health/deep endpoint for comprehensive health status
- The lifespan startup hook for boot-time validation
- The periodic background task for continuous monitoring
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("llm_council.health_probe")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Health Status Tracking                                             ║
# ╚══════════════════════════════════════════════════════════════════════╝

class HealthProbeAgent:
    """Tracks backend subsystem health with history and auto-diagnostics."""

    def __init__(self, max_history: int = 100):
        self._history: List[Dict[str, Any]] = []
        self._max_history = max_history
        self._start_time = time.monotonic()
        self._boot_time = datetime.now(timezone.utc).isoformat()
        self._consecutive_failures: Dict[str, int] = {}
        self._last_status: Dict[str, str] = {}

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def uptime_human(self) -> str:
        s = int(self.uptime_seconds)
        days, remainder = divmod(s, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        parts.append(f"{secs}s")
        return " ".join(parts)

    async def check_cosmos_db(self) -> Dict[str, Any]:
        """Check Cosmos DB connectivity."""
        try:
            from . import storage
            # Try a lightweight operation
            ok = hasattr(storage, '_cosmos_client') or hasattr(storage, '_get_cosmos_container')
            # Attempt actual connection by listing one conversation
            from .storage import _get_cosmos_container
            container = _get_cosmos_container()
            if container:
                # Quick query to verify connectivity
                items = list(container.query_items(
                    query="SELECT TOP 1 c.id FROM c",
                    enable_cross_partition_query=True,
                    max_item_count=1,
                ))
                return {"status": "ok", "backend": "cosmos_db", "reachable": True}
            else:
                return {"status": "ok", "backend": "local_files", "reachable": True}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    async def check_api_key(self) -> Dict[str, Any]:
        """Check API key validity."""
        try:
            from .config import OPENROUTER_API_KEY
            if not OPENROUTER_API_KEY:
                return {"status": "error", "error": "No API key configured"}
            if OPENROUTER_API_KEY.startswith("mga-"):
                return {"status": "ok", "type": "persistent_key", "expires": "never"}
            # JWT token — check expiry
            import base64
            import json
            payload = OPENROUTER_API_KEY.split('.')[1]
            payload += '=' * (4 - len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload))
            exp = decoded.get('exp', 0)
            exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
            remaining = (exp_dt - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                return {"status": "critical", "type": "jwt", "error": "Token EXPIRED", "expired_at": exp_dt.isoformat()}
            elif remaining <= 600:  # 10 min
                return {"status": "warning", "type": "jwt", "remaining_minutes": round(remaining / 60, 1)}
            else:
                return {"status": "ok", "type": "jwt", "remaining_minutes": round(remaining / 60, 1)}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    async def check_memory_store(self) -> Dict[str, Any]:
        """Check memory store availability."""
        try:
            from .memory_store import get_memory_backend
            backend = get_memory_backend()
            backend_type = type(backend).__name__
            return {"status": "ok", "backend": backend_type}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    async def check_models(self) -> Dict[str, Any]:
        """Check model availability."""
        try:
            from .model_sync import get_live_models, get_sync_status
            live = get_live_models()
            sync = get_sync_status()
            return {
                "status": "ok" if live else "warning",
                "model_count": len(live),
                "last_sync": sync.get("last_sync"),
                "sync_source": sync.get("source", "unknown"),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    async def check_resilience(self) -> Dict[str, Any]:
        """Check resilience subsystem (kill switch, circuit breaker)."""
        try:
            from .resilience import kill_switch, circuit_breaker, health_monitor
            status = health_monitor.full_status()
            return {
                "status": "ok",
                "kill_switch_active": kill_switch.active if hasattr(kill_switch, 'active') else status.get("kill_switch", {}).get("is_halted", False),
                "circuit_breaker": status.get("circuit_breaker", {}),
                "healing_actions_total": status.get("healing_actions_total", 0),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    async def run_deep_check(self) -> Dict[str, Any]:
        """Run all health checks in parallel and return comprehensive status."""
        t0 = time.monotonic()

        checks = await asyncio.gather(
            self.check_cosmos_db(),
            self.check_api_key(),
            self.check_memory_store(),
            self.check_models(),
            self.check_resilience(),
            return_exceptions=True,
        )

        check_names = ["cosmos_db", "api_key", "memory_store", "models", "resilience"]
        subsystems = {}
        overall = "ok"

        for name, result in zip(check_names, checks):
            if isinstance(result, Exception):
                subsystems[name] = {"status": "error", "error": str(result)[:200]}
                overall = "degraded"
            else:
                subsystems[name] = result
                status = result.get("status", "unknown")
                if status == "critical":
                    overall = "critical"
                elif status == "error" and overall != "critical":
                    overall = "degraded"
                elif status == "warning" and overall == "ok":
                    overall = "warning"

            # Track consecutive failures
            s = subsystems[name].get("status", "error")
            if s in ("error", "critical"):
                self._consecutive_failures[name] = self._consecutive_failures.get(name, 0) + 1
            else:
                self._consecutive_failures[name] = 0
            self._last_status[name] = s

        elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

        result = {
            "status": overall,
            "uptime": self.uptime_human,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "boot_time": self._boot_time,
            "check_duration_ms": elapsed_ms,
            "subsystems": subsystems,
            "consecutive_failures": {k: v for k, v in self._consecutive_failures.items() if v > 0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Store in history
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return result

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent health check history."""
        return self._history[-limit:]

    def get_failure_report(self) -> Dict[str, Any]:
        """Get a report of subsystems with consecutive failures."""
        failing = {k: v for k, v in self._consecutive_failures.items() if v >= 3}
        return {
            "failing_subsystems": failing,
            "total_checks": len(self._history),
            "last_check": self._history[-1] if self._history else None,
        }


# Singleton instance
health_agent = HealthProbeAgent()


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Periodic Background Monitor                                        ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def periodic_health_check(interval_seconds: int = 300):
    """Background task: run deep health check every N seconds.
    
    Default: every 5 minutes. Logs warnings for degraded/critical status.
    """
    logger.info(f"🏥 Health probe agent started (interval={interval_seconds}s)")
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            result = await health_agent.run_deep_check()
            status = result["status"]
            
            if status == "critical":
                logger.critical(f"🚨 HEALTH CRITICAL: {result['subsystems']}")
            elif status == "degraded":
                logger.warning(f"⚠️ HEALTH DEGRADED: {result['consecutive_failures']}")
            elif status == "warning":
                logger.warning(f"🟡 HEALTH WARNING: {result['subsystems']}")
            else:
                logger.debug(f"✅ Health OK (uptime: {result['uptime']})")

            # Alert on sustained failures (3+ consecutive)
            for subsystem, count in result.get("consecutive_failures", {}).items():
                if count >= 3:
                    logger.error(
                        f"🔴 Subsystem '{subsystem}' has failed {count} consecutive checks!"
                    )
        except asyncio.CancelledError:
            logger.info("🏥 Health probe agent stopped")
            break
        except Exception as e:
            logger.error(f"Health probe error: {e}")
