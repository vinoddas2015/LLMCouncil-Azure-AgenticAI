import { useState, useEffect } from 'react';
import ThemeToggle from './ThemeToggle';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onOpenSettings,
  onExportConversation,
  onDeleteConversation,
  onLogout,
  userDisplayName,
}) {
  const [showMenu, setShowMenu] = useState(null);

  const handleContextMenu = (e, convId) => {
    e.preventDefault();
    setShowMenu(convId);
  };

  const handleMenuAction = (action, convId) => {
    if (action === 'export') {
      onExportConversation?.(convId);
    } else if (action === 'delete') {
      onDeleteConversation?.(convId);
    }
    setShowMenu(null);
  };

  // Close menu when clicking outside
  useEffect(() => {
    const handleClick = () => setShowMenu(null);
    document.addEventListener('click', handleClick);
    return () => document.removeEventListener('click', handleClick);
  }, []);

  return (
    <div className="sidebar" role="navigation" aria-label="Conversations">
      <div className="sidebar-header">
        <div className="logo-container">
          <img src={`${import.meta.env.BASE_URL}Logo_Bayer.jpg`} alt="Bayer Logo" className="bayer-logo" />
          <h1>LLM Council</h1>
        </div>
        <div className="header-actions">
          <ThemeToggle />
          <button 
            className="settings-btn" 
            onClick={onOpenSettings}
            title="Council Settings"
            aria-label="Open council settings"
          >
            ⚙️
          </button>
        </div>
      </div>

      <button
        className="new-conversation-btn"
        onClick={onNewConversation}
        aria-label="Start a new conversation"
      >
        + New Conversation
      </button>

      <div className="conversation-list" role="listbox" aria-label="Conversation history">
        {conversations.length === 0 ? (
          <div className="no-conversations" role="status">No conversations yet</div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              role="option"
              aria-selected={conv.id === currentConversationId}
              tabIndex={0}
              onClick={() => onSelectConversation(conv.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelectConversation(conv.id);
                }
              }}
              onContextMenu={(e) => handleContextMenu(e, conv.id)}
            >
              <div className="conversation-title">
                {conv.title || 'New Conversation'}
              </div>
              <div className="conversation-meta">
                {conv.message_count} messages
                {conv.context_tags?.domain && conv.context_tags.domain !== 'general' && (
                  <span className="domain-tag" title={`Domain: ${conv.context_tags.domain}`}>
                    {conv.context_tags.domain}
                  </span>
                )}
              </div>
              <button 
                className="conv-menu-btn"
                aria-label={`Actions for ${conv.title || 'conversation'}`}
                aria-expanded={showMenu === conv.id}
                aria-haspopup="menu"
                onClick={(e) => {
                  e.stopPropagation();
                  setShowMenu(showMenu === conv.id ? null : conv.id);
                }}
              >
                ⋮
              </button>
              {showMenu === conv.id && (
                <div className="conv-menu" role="menu" onClick={(e) => e.stopPropagation()}>
                  <button role="menuitem" onClick={() => handleMenuAction('export', conv.id)}>
                    📥 Export
                  </button>
                  <button 
                    className="delete-action"
                    role="menuitem"
                    onClick={() => handleMenuAction('delete', conv.id)}
                  >
                    🗑️ Delete
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <div className="sidebar-footer">
        {onLogout && (
          <button
            className="sidebar-sign-out"
            onClick={onLogout}
            title="Sign out of your Bayer account"
            aria-label="Sign out of your Bayer account"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            Sign Out
          </button>
        )}
        {userDisplayName && <span className="footer-user-id" title={userDisplayName}>{userDisplayName}</span>}
        <span className="powered-by">Queries contact: <a href="mailto:llmcouncil@bayer.com" className="footer-email">llmcouncil@bayer.com</a></span>
      </div>
    </div>
  );
}
