'use client';

import { useState, useEffect, useCallback } from 'react';
import { CloseButton } from '@autoswarm/ui';
import { apiFetch } from '@/lib/api';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useToast } from '@/hooks/useToast';
import { logger } from '@/lib/logger';

interface ConnectedUser {
  session_id: string;
  name: string;
  status: string;
}

interface AdminPanelProps {
  isOpen: boolean;
  onClose: () => void;
  isAdmin: boolean;
}

/**
 * Admin panel for managing connected users and room configuration.
 * Only rendered when the user has the admin role.
 */
export function AdminPanel({ isOpen, onClose, isAdmin }: AdminPanelProps) {
  const [users, setUsers] = useState<ConnectedUser[]>([]);
  const [motd, setMotd] = useState('');
  const [loading, setLoading] = useState(false);
  const { addToast } = useToast();

  const fetchUsers = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const resp = await apiFetch('/api/v1/admin/users');
      if (resp.ok) {
        setUsers(await resp.json());
      } else {
        // Non-2xx is surfaced — admin opening the panel deserves to know
        // when their session lacks the role or the API is down.
        logger.warn('AdminPanel: /admin/users returned', resp.status);
        addToast(`Failed to load users (HTTP ${resp.status})`, 'error');
      }
    } catch (err) {
      logger.error('AdminPanel: fetchUsers failed', err);
      addToast('Failed to load users — check connection', 'error');
    }
  }, [isAdmin, addToast]);

  useEffect(() => {
    if (isOpen && isAdmin) {
      fetchUsers();
    }
  }, [isOpen, isAdmin, fetchUsers]);

  const handleKick = useCallback(
    async (sessionId: string) => {
      setLoading(true);
      try {
        const resp = await apiFetch('/api/v1/admin/kick', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId }),
        });
        if (resp.ok) {
          addToast('User kicked', 'success');
          await fetchUsers();
        } else {
          logger.warn('AdminPanel: kick returned', resp.status);
          addToast(`Kick failed (HTTP ${resp.status})`, 'error');
        }
      } catch (err) {
        logger.error('AdminPanel: kick failed', err);
        addToast('Kick failed — check connection', 'error');
      } finally {
        setLoading(false);
      }
    },
    [fetchUsers, addToast]
  );

  const handleMotdUpdate = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await apiFetch('/api/v1/admin/room-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ motd }),
      });
      if (resp.ok) {
        addToast('MOTD updated', 'success');
      } else {
        logger.warn('AdminPanel: room-config returned', resp.status);
        addToast(`MOTD update failed (HTTP ${resp.status})`, 'error');
      }
    } catch (err) {
      logger.error('AdminPanel: handleMotdUpdate failed', err);
      addToast('MOTD update failed — check connection', 'error');
    } finally {
      setLoading(false);
    }
  }, [motd, addToast]);

  // ESC to close
  useEffect(() => {
    if (!isOpen || !isAdmin) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, isAdmin, onClose]);

  const focusTrapRef = useFocusTrap<HTMLDivElement>(isOpen && isAdmin);

  if (!isOpen || !isAdmin) return null;

  return (
    <div
      ref={focusTrapRef}
      className="fixed right-0 top-0 h-full w-full max-w-80 sm:w-80 retro-panel z-modal animate-slide-in-right flex flex-col"
      role="dialog"
      aria-modal="true"
      aria-labelledby="admin-panel-title"
    >
      <div className="flex items-center justify-between p-3 border-b border-slate-700">
        <h2 id="admin-panel-title" className="text-retro-base font-bold text-slate-200">Admin</h2>
        <CloseButton onClick={onClose} label="Close admin panel" shortcut="ESC" className="touch-target" />
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {/* Connected Users */}
        <section>
          <h3 className="text-retro-xs font-bold text-slate-300 mb-2">
            Connected Users ({users.length})
          </h3>
          <div className="space-y-1">
            {users.map((u) => (
              <div
                key={u.session_id}
                className="flex items-center justify-between p-2 rounded bg-slate-800/50"
              >
                <span className="text-retro-xs text-slate-200 truncate">
                  {u.name}
                </span>
                <button
                  onClick={() => handleKick(u.session_id)}
                  disabled={loading}
                  className="pxa-btn touch-target text-retro-xs px-2 py-0.5 bg-red-900/50 hover:bg-red-800/50"
                  aria-label={`Kick ${u.name}`}
                >
                  Kick
                </button>
              </div>
            ))}
          </div>
        </section>

        {/* Room Config */}
        <section>
          <h3 className="text-retro-xs font-bold text-slate-300 mb-2">
            Room Config
          </h3>
          <div className="space-y-2">
            <input
              type="text"
              value={motd}
              onChange={(e) => setMotd(e.target.value)}
              placeholder="Message of the day..."
              maxLength={500}
              className="pxa-input w-full text-retro-xs"
            />
            <button
              onClick={handleMotdUpdate}
              disabled={loading}
              className="pxa-btn text-retro-xs px-3 py-1 w-full"
            >
              Update MOTD
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
