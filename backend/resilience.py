"""
Self-healing, headless resilience, and kill switch infrastructure for LLM Council.

Provides:
- Kill Switch: Global abort mechanism accessible to end users
- Circuit Breaker: Per-model failure tracking with automatic disabling/recovery
- Retry with Exponential Backoff: Transparent retries for transient failures
- Fallback Model Resolution: Automatic substitution when a model is unavailable
- Quorum Enforcement: Ensures minimum viable responses before proceeding
- Health Monitor: Tracks model health for headless self-healing decisions
"""

import asyncio
import time
import logging
from typing import Dict, Optional, List, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("llm_council.resilience")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Kill Switch — global, thread-safe abort mechanism
# ---------------------------------------------------------------------------

class KillSwitch:
    """
    Global kill switch that end users can trigger to abort ALL in-flight
    council operations immediately.  Designed as a singleton.
    """

    def __init__(self):
        self._active_sessions: Dict[str, asyncio.Event] = {}
        self._global_halt = False
        self._halt_reason: Optional[str] = None
        self._halt_timestamp: Optional[float] = None
        # Counters
        self._total_kills = 0

    # -- Session-scoped abort (per conversation) --

    def register_session(self, session_id: str) -> asyncio.Event:
        """Register a new streaming session. Returns an Event that is SET when killed."""
        evt = asyncio.Event()
        self._active_sessions[session_id] = evt
        logger.info(f"[KillSwitch] Session registered: {session_id}")
        return evt

    def unregister_session(self, session_id: str):
        """Clean up after a session completes or is killed."""
        self._active_sessions.pop(session_id, None)
        logger.info(f"[KillSwitch] Session unregistered: {session_id}")

    def kill_session(self, session_id: str, reason: str = "User triggered kill switch"):
        """Kill a specific session."""
        evt = self._active_sessions.get(session_id)
        if evt:
            evt.set()
            self._total_kills += 1
            logger.warning(f"[KillSwitch] Session KILLED: {session_id} — {reason}")
            return True
        return False

    def is_session_killed(self, session_id: str) -> bool:
        """Check if a specific session has been killed."""
        evt = self._active_sessions.get(session_id)
        if evt and evt.is_set():
            return True
        return self._global_halt

    # -- Global halt (emergency stop for ALL sessions) --

    def global_halt(self, reason: str = "Emergency halt triggered by user"):
        """Kill ALL active sessions and prevent new ones from proceeding."""
        self._global_halt = True
        self._halt_reason = reason
        self._halt_timestamp = time.time()
        self._total_kills += len(self._active_sessions)
        for sid, evt in self._active_sessions.items():
            evt.set()
            logger.warning(f"[KillSwitch] Global halt — killed session: {sid}")
        logger.critical(f"[KillSwitch] GLOBAL HALT ACTIVATED: {reason}")

    def release_global_halt(self):
        """Release the global halt so new sessions can proceed."""
        self._global_halt = False
        self._halt_reason = None
        self._halt_timestamp = None
        logger.info("[KillSwitch] Global halt RELEASED")

    @property
    def is_halted(self) -> bool:
        return self._global_halt

    def status(self) -> dict:
        """Return full kill switch status for the API."""
        return {
            "global_halt": self._global_halt,
            "halt_reason": self._halt_reason,
            "halt_timestamp": self._halt_timestamp,
            "active_sessions": list(self._active_sessions.keys()),
            "active_session_count": len(self._active_sessions),
            "total_kills": self._total_kills,
        }


# Singleton
kill_switch = KillSwitch()


# ---------------------------------------------------------------------------
# Circuit Breaker — per-model failure tracking
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Model disabled due to failures
    HALF_OPEN = "half_open"  # Tentative recovery attempt


@dataclass
class ModelCircuit:
    """Circuit breaker state for a single model."""
    model: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    last_error: Optional[str] = None

    # Thresholds
    failure_threshold: int = 3           # Failures before opening circuit
    recovery_timeout: float = 120.0      # Seconds before attempting recovery
    half_open_max_attempts: int = 1      # Attempts allowed in half-open state


class CircuitBreaker:
    """
    Tracks per-model health. If a model fails repeatedly, the circuit
    opens and queries are routed to fallback models automatically.
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 120.0):
        self._circuits: Dict[str, ModelCircuit] = {}
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout

    def _get_circuit(self, model: str) -> ModelCircuit:
        if model not in self._circuits:
            self._circuits[model] = ModelCircuit(
                model=model,
                failure_threshold=self._failure_threshold,
                recovery_timeout=self._recovery_timeout,
            )
        return self._circuits[model]

    def can_attempt(self, model: str) -> bool:
        """Check whether a query to this model is allowed."""
        circuit = self._get_circuit(model)

        if circuit.state == CircuitState.CLOSED:
            return True

        if circuit.state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            elapsed = time.time() - circuit.last_failure_time
            if elapsed >= circuit.recovery_timeout:
                circuit.state = CircuitState.HALF_OPEN
                logger.info(f"[CircuitBreaker] {model}: OPEN → HALF_OPEN (recovery attempt)")
                return True
            return False

        if circuit.state == CircuitState.HALF_OPEN:
            return True

        return False

    def record_success(self, model: str):
        """Record a successful query — resets failure tracking."""
        circuit = self._get_circuit(model)
        circuit.success_count += 1
        circuit.last_success_time = time.time()

        if circuit.state == CircuitState.HALF_OPEN:
            circuit.state = CircuitState.CLOSED
            circuit.failure_count = 0
            logger.info(f"[CircuitBreaker] {model}: HALF_OPEN → CLOSED (recovered)")
        elif circuit.state == CircuitState.CLOSED:
            circuit.failure_count = 0

    def record_failure(self, model: str, error: str):
        """Record a failure. Opens circuit if threshold exceeded."""
        circuit = self._get_circuit(model)
        circuit.failure_count += 1
        circuit.last_failure_time = time.time()
        circuit.last_error = error

        if circuit.state == CircuitState.HALF_OPEN:
            circuit.state = CircuitState.OPEN
            logger.warning(f"[CircuitBreaker] {model}: HALF_OPEN → OPEN (recovery failed)")
        elif circuit.failure_count >= circuit.failure_threshold:
            circuit.state = CircuitState.OPEN
            logger.warning(
                f"[CircuitBreaker] {model}: CLOSED → OPEN "
                f"(failures={circuit.failure_count}, threshold={circuit.failure_threshold})"
            )

    def get_healthy_models(self, models: List[str]) -> List[str]:
        """Filter a list of models down to those whose circuit is not OPEN."""
        return [m for m in models if self.can_attempt(m)]

    def reset(self, model: Optional[str] = None):
        """Manually reset one or all circuits (admin recovery)."""
        if model:
            if model in self._circuits:
                self._circuits[model] = ModelCircuit(
                    model=model,
                    failure_threshold=self._failure_threshold,
                    recovery_timeout=self._recovery_timeout,
                )
                logger.info(f"[CircuitBreaker] {model}: manually reset")
        else:
            self._circuits.clear()
            logger.info("[CircuitBreaker] ALL circuits reset")

    def status(self) -> dict:
        """Return full circuit breaker status for the API."""
        return {
            model: {
                "state": circuit.state.value,
                "failure_count": circuit.failure_count,
                "success_count": circuit.success_count,
                "last_error": circuit.last_error,
                "last_failure_time": circuit.last_failure_time,
                "last_success_time": circuit.last_success_time,
            }
            for model, circuit in self._circuits.items()
        }


# Singleton
circuit_breaker = CircuitBreaker()


# ---------------------------------------------------------------------------
# Retry with exponential backoff
# ---------------------------------------------------------------------------

async def retry_with_backoff(
    fn,
    *args,
    max_retries: int = 2,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    session_id: Optional[str] = None,
    **kwargs,
):
    """
    Execute an async function with exponential backoff retries.
    Respects the kill switch — aborts immediately if session is killed.

    Args:
        fn: Async callable to retry
        max_retries: Maximum number of retry attempts (0 = no retries)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap
        session_id: Optional session ID for kill switch checks

    Returns:
        The result of fn, or None if all attempts failed

    Raises:
        KillSwitchError: If session was killed during retries
    """
    last_error = None

    for attempt in range(max_retries + 1):
        # Kill switch check
        if session_id and kill_switch.is_session_killed(session_id):
            raise KillSwitchError(f"Session {session_id} was killed")
        if kill_switch.is_halted:
            raise KillSwitchError("Global halt is active")

        try:
            result = await fn(*args, **kwargs)
            return result
        except KillSwitchError:
            raise
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    f"[Retry] Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"[Retry] All {max_retries + 1} attempts failed. Last error: {e}"
                )

    return None


# ---------------------------------------------------------------------------
# Fallback Model Resolution
# ---------------------------------------------------------------------------

# Ordered fallback chains per model — if the primary fails, try these in order
FALLBACK_CHAINS: Dict[str, List[str]] = {
    "claude-opus-4.5":   ["gemini-2.5-pro", "gpt-5-mini", "grok-3"],
    "gemini-2.5-pro":    ["claude-opus-4.5", "gpt-5-mini", "grok-3"],
    "gpt-5-mini":        ["gemini-2.5-flash", "gemini-2.5-pro", "claude-opus-4.5"],
    "grok-3":            ["gemini-2.5-pro", "claude-opus-4.5", "gpt-5-mini"],
    "gemini-2.5-flash":  ["gpt-5-mini", "gemini-2.5-pro"],
}


def resolve_fallback(
    failed_model: str,
    already_used: Set[str],
) -> Optional[str]:
    """
    Find the best available fallback model for a failed model.

    Args:
        failed_model: The model that failed
        already_used: Set of models already in use (to avoid duplicates)

    Returns:
        A fallback model ID, or None if no fallback available
    """
    chain = FALLBACK_CHAINS.get(failed_model, [])
    for candidate in chain:
        if candidate not in already_used and circuit_breaker.can_attempt(candidate):
            logger.info(f"[Fallback] {failed_model} → {candidate}")
            return candidate

    logger.warning(f"[Fallback] No fallback available for {failed_model}")
    return None


# ---------------------------------------------------------------------------
# Quorum Enforcement
# ---------------------------------------------------------------------------

MIN_STAGE1_QUORUM = 2   # Minimum models needed for Stage 1
MIN_STAGE2_QUORUM = 2   # Minimum rankers needed for Stage 2


def check_quorum(results: list, stage: str, minimum: int) -> bool:
    """
    Check if we have enough successful responses to proceed.

    Args:
        results: List of results (non-None entries count)
        stage: Stage name for logging
        minimum: Minimum required count

    Returns:
        True if quorum met
    """
    count = len(results)
    met = count >= minimum
    if not met:
        logger.error(
            f"[Quorum] {stage}: FAILED — got {count} responses, need {minimum}"
        )
    else:
        logger.info(
            f"[Quorum] {stage}: OK — got {count} responses (min={minimum})"
        )
    return met


# ---------------------------------------------------------------------------
# Health Monitor — aggregated status for the entire system
# ---------------------------------------------------------------------------

class HealthMonitor:
    """
    Tracks overall system health: model availability, recent failures,
    and self-healing actions taken.
    """

    def __init__(self):
        self._healing_log: List[dict] = []
        self._max_log_size = 200

    def log_healing_action(self, action: str, details: dict):
        """Record a self-healing action that was taken."""
        entry = {
            "timestamp": time.time(),
            "action": action,
            **details,
        }
        self._healing_log.append(entry)
        if len(self._healing_log) > self._max_log_size:
            self._healing_log = self._healing_log[-self._max_log_size:]
        logger.info(f"[HealthMonitor] {action}: {details}")

    def full_status(self) -> dict:
        """Return complete system health status."""
        return {
            "kill_switch": kill_switch.status(),
            "circuit_breaker": circuit_breaker.status(),
            "recent_healing_actions": self._healing_log[-20:],
            "healing_actions_total": len(self._healing_log),
        }


# Singleton
health_monitor = HealthMonitor()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class KillSwitchError(Exception):
    """Raised when a kill switch abort is detected."""
    pass


class QuorumError(Exception):
    """Raised when quorum cannot be met even after self-healing."""
    pass
