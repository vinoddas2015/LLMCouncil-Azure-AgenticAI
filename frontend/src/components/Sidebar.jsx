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
          <img src="/Logo_Bayer.jpg" alt="Bayer Logo" className="bayer-logo" />
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
        <span className="powered-by">Queries contact: <a href="mailto:llmcouncil@bayer.com" className="footer-email">llmcouncil@bayer.com</a></span>
      </div>
    </div>
  );
}
