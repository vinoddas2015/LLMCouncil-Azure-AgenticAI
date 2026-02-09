import { useState, useEffect } from 'react';
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
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="logo-container">
          <img src="/Logo_Bayer.jpg" alt="Bayer" className="bayer-logo" />
          <h1>LLM Council</h1>
        </div>
        <div className="header-actions">
          <button 
            className="settings-btn" 
            onClick={onOpenSettings}
            title="Council Settings"
          >
            ⚙️
          </button>
        </div>
      </div>

      <button className="new-conversation-btn" onClick={onNewConversation}>
        + New Conversation
      </button>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">No conversations yet</div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              onClick={() => onSelectConversation(conv.id)}
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
                onClick={(e) => {
                  e.stopPropagation();
                  setShowMenu(showMenu === conv.id ? null : conv.id);
                }}
              >
                ⋮
              </button>
              {showMenu === conv.id && (
                <div className="conv-menu" onClick={(e) => e.stopPropagation()}>
                  <button onClick={() => handleMenuAction('export', conv.id)}>
                    📥 Export
                  </button>
                  <button 
                    className="delete-action"
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
