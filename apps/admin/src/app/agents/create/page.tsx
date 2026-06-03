'use client';

import { useState, useEffect, useCallback } from 'react';
import type { AgentRole, Department } from '@selva/shared-types';
import { Button } from '@selva/ui';
import { apiFetch } from '@/lib/api';

const AGENT_ROLES: AgentRole[] = [
  'planner',
  'coder',
  'reviewer',
  'researcher',
  'crm',
  'support',
];

export default function CreateAgentPage() {
  const [name, setName] = useState('');
  const [role, setRole] = useState<AgentRole>('coder');
  const [departmentId, setDepartmentId] = useState('');
  const [departments, setDepartments] = useState<Department[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const fetchDepartments = useCallback(async () => {
    try {
      const res = await apiFetch('/api/v1/departments');
      if (res.ok) {
        setDepartments(await res.json());
      }
    } catch {
      // Non-critical: department select will be empty
    }
  }, []);

  useEffect(() => {
    fetchDepartments();
  }, [fetchDepartments]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!name.trim()) {
      setError('Name is required');
      return;
    }

    setSubmitting(true);
    setError(null);
    setSuccess(false);

    try {
      const body: Record<string, unknown> = { name: name.trim(), role };
      if (departmentId) {
        body.departmentId = departmentId;
      }

      const res = await apiFetch('/api/v1/agents', {
        method: 'POST',
        body: JSON.stringify(body),
      });

      if (res.ok) {
        setSuccess(true);
        setName('');
        setRole('coder');
        setDepartmentId('');
      } else {
        const data = await res.json().catch(() => ({}));
        setError(data.detail ?? 'Failed to create agent');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 px-6 py-8">
      <header className="mb-6">
        <nav className="mb-4">
          <a
            href="/agents"
            className="font-mono text-xs text-slate-500 hover:text-indigo-400"
          >
            &lt; Back to Agents
          </a>
        </nav>
        <h1 className="font-mono text-xl font-bold uppercase tracking-widest text-indigo-400">
          Create Agent
        </h1>
        <p className="mt-1 font-mono text-sm text-slate-500">
          Add a new AI agent to the office
        </p>
      </header>

      {error && (
        <div className="mb-4 bg-red-900/30 px-4 py-3 font-mono text-sm text-red-400">
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-4 text-red-300 hover:text-white"
          >
            Dismiss
          </button>
        </div>
      )}

      {success && (
        <div className="mb-4 bg-emerald-900/30 px-4 py-3 font-mono text-sm text-emerald-400">
          Agent created successfully!
        </div>
      )}

      <form onSubmit={handleSubmit} className="max-w-md space-y-5">
        {/* Name */}
        <div>
          <label
            htmlFor="agent-name"
            className="mb-1 block font-mono text-xs font-bold uppercase tracking-wider text-slate-400"
          >
            Name
          </label>
          <input
            id="agent-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Agent Alpha"
            className="w-full border border-slate-600 bg-slate-800 px-3 py-2 font-mono text-sm text-white placeholder-slate-600 focus:border-indigo-500 focus:outline-none"
            required
          />
        </div>

        {/* Role */}
        <div>
          <label
            htmlFor="agent-role"
            className="mb-1 block font-mono text-xs font-bold uppercase tracking-wider text-slate-400"
          >
            Role
          </label>
          <select
            id="agent-role"
            value={role}
            onChange={(e) => setRole(e.target.value as AgentRole)}
            className="w-full border border-slate-600 bg-slate-800 px-3 py-2 font-mono text-sm text-white focus:border-indigo-500 focus:outline-none"
          >
            {AGENT_ROLES.map((r) => (
              <option key={r} value={r}>
                {r.charAt(0).toUpperCase() + r.slice(1)}
              </option>
            ))}
          </select>
        </div>

        {/* Department */}
        <div>
          <label
            htmlFor="agent-department"
            className="mb-1 block font-mono text-xs font-bold uppercase tracking-wider text-slate-400"
          >
            Department
          </label>
          <select
            id="agent-department"
            value={departmentId}
            onChange={(e) => setDepartmentId(e.target.value)}
            className="w-full border border-slate-600 bg-slate-800 px-3 py-2 font-mono text-sm text-white focus:border-indigo-500 focus:outline-none"
          >
            <option value="">Unassigned</option>
            {departments.map((dept) => (
              <option key={dept.id} value={dept.id}>
                {dept.name}
              </option>
            ))}
          </select>
        </div>

        <Button
          type="submit"
          disabled={submitting}
          variant="approve"
        >
          {submitting ? 'Creating...' : 'Create Agent'}
        </Button>
      </form>
    </div>
  );
}
