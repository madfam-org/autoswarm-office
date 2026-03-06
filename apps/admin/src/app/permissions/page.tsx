'use client';

import { useState, useEffect, useCallback } from 'react';
import type {
  ActionCategory,
  PermissionLevel,
  PermissionMatrix,
} from '@autoswarm/shared-types';
import { Button } from '@autoswarm/ui';

const NEXUS_API_URL =
  process.env.NEXT_PUBLIC_NEXUS_API_URL ?? 'http://localhost:4300';

const ACTION_CATEGORIES: { key: ActionCategory; label: string; description: string }[] = [
  { key: 'file_read', label: 'File Read', description: 'Read files from the filesystem' },
  { key: 'file_write', label: 'File Write', description: 'Write or modify files' },
  { key: 'bash_execute', label: 'Bash Execute', description: 'Run shell commands' },
  { key: 'git_commit', label: 'Git Commit', description: 'Create git commits' },
  { key: 'git_push', label: 'Git Push', description: 'Push to remote repository' },
  { key: 'email_send', label: 'Email Send', description: 'Send emails on behalf of the org' },
  { key: 'crm_update', label: 'CRM Update', description: 'Modify CRM records' },
  { key: 'deploy', label: 'Deploy', description: 'Deploy to staging or production' },
  { key: 'api_call', label: 'API Call', description: 'Make external API requests' },
];

const PERMISSION_LEVELS: { key: PermissionLevel; label: string; color: string; activeColor: string }[] = [
  {
    key: 'allow',
    label: 'Allow',
    color: 'text-emerald-400 border-emerald-700',
    activeColor: 'bg-emerald-700 text-white border-emerald-500',
  },
  {
    key: 'ask',
    label: 'Ask',
    color: 'text-amber-400 border-amber-700',
    activeColor: 'bg-amber-700 text-white border-amber-500',
  },
  {
    key: 'deny',
    label: 'Deny',
    color: 'text-red-400 border-red-700',
    activeColor: 'bg-red-700 text-white border-red-500',
  },
];

const DEFAULT_MATRIX: PermissionMatrix = {
  file_read: 'allow',
  file_write: 'ask',
  bash_execute: 'ask',
  git_commit: 'ask',
  git_push: 'deny',
  email_send: 'deny',
  crm_update: 'ask',
  deploy: 'deny',
  api_call: 'ask',
};

export default function PermissionsPage() {
  const [matrix, setMatrix] = useState<PermissionMatrix>(DEFAULT_MATRIX);
  const [originalMatrix, setOriginalMatrix] = useState<PermissionMatrix>(DEFAULT_MATRIX);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const fetchMatrix = useCallback(async () => {
    try {
      const res = await fetch(`${NEXUS_API_URL}/api/v1/permissions/matrix`);
      if (res.ok) {
        const data: PermissionMatrix = await res.json();
        setMatrix(data);
        setOriginalMatrix(data);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load permissions',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMatrix();
  }, [fetchMatrix]);

  const handleToggle = (category: ActionCategory, level: PermissionLevel) => {
    setMatrix((prev) => ({ ...prev, [category]: level }));
    setSaveSuccess(false);
  };

  const hasChanges = Object.keys(matrix).some(
    (key) =>
      matrix[key as ActionCategory] !== originalMatrix[key as ActionCategory],
  );

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSaveSuccess(false);

    try {
      const res = await fetch(`${NEXUS_API_URL}/api/v1/permissions/matrix`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(matrix),
      });

      if (res.ok) {
        setOriginalMatrix({ ...matrix });
        setSaveSuccess(true);
      } else {
        const body = await res.text();
        setError(`Failed to save: ${body}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setMatrix({ ...originalMatrix });
    setSaveSuccess(false);
  };

  return (
    <div className="min-h-screen bg-slate-900 px-6 py-8">
      {/* Header */}
      <header className="mb-6">
        <nav className="mb-4">
          <a
            href="/"
            className="font-mono text-xs text-slate-500 hover:text-indigo-400"
          >
            &lt; Back to Dashboard
          </a>
        </nav>
        <h1 className="font-mono text-xl font-bold uppercase tracking-widest text-indigo-400">
          Permission Matrix
        </h1>
        <p className="mt-1 font-mono text-sm text-slate-500">
          Configure which actions agents can perform autonomously, require
          approval, or are blocked
        </p>
      </header>

      {error && (
        <div className="mb-4 bg-red-900/30 px-4 py-3 pixel-border font-mono text-sm text-red-400">
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-4 text-red-300 hover:text-white"
          >
            Dismiss
          </button>
        </div>
      )}

      {saveSuccess && (
        <div className="mb-4 bg-emerald-900/30 px-4 py-3 pixel-border font-mono text-sm text-emerald-400">
          Permission matrix saved successfully.
        </div>
      )}

      {loading ? (
        <p className="py-20 text-center font-mono text-sm text-slate-500 animate-pulse">
          Loading permissions...
        </p>
      ) : (
        <>
          {/* Permission grid */}
          <div className="mb-6 overflow-x-auto">
            <table className="w-full font-mono text-sm">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="px-4 py-3 text-left text-[10px] uppercase tracking-wider text-slate-500">
                    Action Category
                  </th>
                  {PERMISSION_LEVELS.map((level) => (
                    <th
                      key={level.key}
                      className="px-4 py-3 text-center text-[10px] uppercase tracking-wider text-slate-500"
                    >
                      {level.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ACTION_CATEGORIES.map((category) => (
                  <tr
                    key={category.key}
                    className="border-b border-slate-800 transition-colors hover:bg-slate-800/30"
                  >
                    <td className="px-4 py-3">
                      <div>
                        <p className="font-bold text-white">{category.label}</p>
                        <p className="text-[10px] text-slate-500">
                          {category.description}
                        </p>
                      </div>
                    </td>
                    {PERMISSION_LEVELS.map((level) => {
                      const isActive = matrix[category.key] === level.key;
                      const changed =
                        originalMatrix[category.key] !== matrix[category.key] &&
                        isActive;

                      return (
                        <td key={level.key} className="px-4 py-3 text-center">
                          <button
                            onClick={() =>
                              handleToggle(category.key, level.key)
                            }
                            className={`inline-flex items-center justify-center px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider border transition-all ${
                              isActive ? level.activeColor : `bg-transparent ${level.color} opacity-40 hover:opacity-70`
                            } ${changed ? 'ring-2 ring-indigo-500 ring-offset-1 ring-offset-slate-900' : ''}`}
                            aria-pressed={isActive}
                            aria-label={`Set ${category.label} to ${level.label}`}
                          >
                            {level.label}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-between border-t border-slate-800 pt-4">
            <div className="font-mono text-xs text-slate-600">
              {hasChanges ? (
                <span className="text-amber-400">Unsaved changes</span>
              ) : (
                <span>No changes</span>
              )}
            </div>
            <div className="flex gap-3">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleReset}
                disabled={!hasChanges}
              >
                Reset
              </Button>
              <Button
                variant="default"
                size="sm"
                onClick={handleSave}
                disabled={!hasChanges || saving}
              >
                {saving ? 'Saving...' : 'Save Matrix'}
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
