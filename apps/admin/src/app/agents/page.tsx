'use client';

import { useState, useEffect, useCallback } from 'react';
import type {
  Agent,
  AgentRole,
  AgentStatus,
  Department,
} from '@autoswarm/shared-types';
import { Button } from '@autoswarm/ui';

const NEXUS_API_URL =
  process.env.NEXT_PUBLIC_NEXUS_API_URL ?? 'http://localhost:4300';

const ROLE_COLORS: Record<AgentRole, string> = {
  planner: 'bg-violet-800 text-violet-200',
  coder: 'bg-cyan-800 text-cyan-200',
  reviewer: 'bg-amber-800 text-amber-200',
  researcher: 'bg-emerald-800 text-emerald-200',
  crm: 'bg-rose-800 text-rose-200',
  support: 'bg-sky-800 text-sky-200',
};

const STATUS_COLORS: Record<AgentStatus, string> = {
  idle: 'text-gray-400',
  working: 'text-blue-400',
  waiting_approval: 'text-amber-400',
  paused: 'text-slate-400',
  error: 'text-red-400',
};

interface EditState {
  agentId: string;
  departmentId: string;
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingReassign, setEditingReassign] = useState<EditState | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [agentsRes, depsRes] = await Promise.all([
        fetch(`${NEXUS_API_URL}/api/v1/agents`),
        fetch(`${NEXUS_API_URL}/api/v1/departments`),
      ]);

      if (agentsRes.ok) {
        setAgents(await agentsRes.json());
      }
      if (depsRes.ok) {
        setDepartments(await depsRes.json());
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load agents');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleDelete = async (agentId: string) => {
    try {
      const res = await fetch(`${NEXUS_API_URL}/api/v1/agents/${agentId}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setAgents((prev) => prev.filter((a) => a.id !== agentId));
      } else {
        setError('Failed to delete agent');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
    setDeleteConfirm(null);
  };

  const handleReassign = async (agentId: string, departmentId: string) => {
    try {
      const res = await fetch(
        `${NEXUS_API_URL}/api/v1/agents/${agentId}/department`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ departmentId }),
        },
      );
      if (res.ok) {
        setAgents((prev) =>
          prev.map((a) => (a.id === agentId ? { ...a, departmentId } : a)),
        );
      } else {
        setError('Failed to reassign agent');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reassign failed');
    }
    setEditingReassign(null);
  };

  const getDepartmentName = (departmentId: string | null): string => {
    if (!departmentId) return 'Unassigned';
    return departments.find((d) => d.id === departmentId)?.name ?? 'Unknown';
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
          Agent Management
        </h1>
        <p className="mt-1 font-mono text-sm text-slate-500">
          View, edit, and manage all AI agents
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

      {loading ? (
        <p className="py-20 text-center font-mono text-sm text-slate-500 animate-pulse">
          Loading agents...
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-sm">
            <thead>
              <tr className="border-b border-slate-700 text-left text-[10px] uppercase tracking-wider text-slate-500">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Department</th>
                <th className="px-4 py-3">Level</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <tr
                  key={agent.id}
                  className="border-b border-slate-800 transition-colors hover:bg-slate-800/50"
                >
                  <td className="px-4 py-3 font-bold text-white">
                    {agent.name}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block px-2 py-0.5 text-[10px] font-bold uppercase ${ROLE_COLORS[agent.role]}`}
                    >
                      {agent.role}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-xs font-bold uppercase ${STATUS_COLORS[agent.status]}`}
                    >
                      {agent.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {editingReassign?.agentId === agent.id ? (
                      <select
                        value={editingReassign.departmentId}
                        onChange={(e) =>
                          setEditingReassign({
                            ...editingReassign,
                            departmentId: e.target.value,
                          })
                        }
                        className="bg-slate-800 px-2 py-1 text-xs text-white border border-slate-600 focus:border-indigo-500 focus:outline-none"
                      >
                        <option value="">Unassigned</option>
                        {departments.map((dept) => (
                          <option key={dept.id} value={dept.id}>
                            {dept.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-slate-300">
                        {getDepartmentName(agent.departmentId)}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="font-bold text-indigo-300">
                      {agent.level}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {editingReassign?.agentId === agent.id ? (
                        <>
                          <Button
                            size="sm"
                            variant="approve"
                            onClick={() =>
                              handleReassign(
                                agent.id,
                                editingReassign.departmentId,
                              )
                            }
                          >
                            Save
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setEditingReassign(null)}
                          >
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              setEditingReassign({
                                agentId: agent.id,
                                departmentId: agent.departmentId ?? '',
                              })
                            }
                          >
                            Reassign
                          </Button>
                          {deleteConfirm === agent.id ? (
                            <>
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={() => handleDelete(agent.id)}
                              >
                                Confirm
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setDeleteConfirm(null)}
                              >
                                Cancel
                              </Button>
                            </>
                          ) : (
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => setDeleteConfirm(agent.id)}
                            >
                              Delete
                            </Button>
                          )}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}

              {agents.length === 0 && (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-12 text-center text-slate-600"
                  >
                    No agents found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
