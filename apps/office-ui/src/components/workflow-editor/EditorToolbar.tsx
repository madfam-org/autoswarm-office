'use client';

import { useRef } from 'react';
import { PixelButton } from '@selva/ui';
import type { WorkflowSummary, WorkflowStatus, ValidationResult } from '@/hooks/useWorkflow';

interface EditorToolbarProps {
  workflowName: string;
  onNameChange: (name: string) => void;
  workflowList: WorkflowSummary[];
  currentWorkflowId: string | null;
  status: WorkflowStatus;
  validationResult: ValidationResult | null;
  onNew: () => void;
  onSave: () => void;
  onLoad: (id: string) => void;
  onExport: () => void;
  onImport: (yaml: string) => void;
  onValidate: () => void;
  onRun: () => void;
  onClose: () => void;
  onOpenTemplates: () => void;
}

export function EditorToolbar({
  workflowName,
  onNameChange,
  workflowList,
  currentWorkflowId,
  status,
  validationResult,
  onNew,
  onSave,
  onLoad,
  onExport,
  onImport,
  onValidate,
  onRun,
  onClose,
  onOpenTemplates,
}: EditorToolbarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleImportClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const content = evt.target?.result;
      if (typeof content === 'string') {
        onImport(content);
      }
    };
    reader.readAsText(file);
    // Reset so re-selecting the same file triggers onChange
    e.target.value = '';
  };

  const validationIcon = validationResult
    ? validationResult.valid
      ? '✅'
      : '❌'
    : '⬜';

  return (
    <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-700 bg-slate-900/90 flex-shrink-0">
      {/* Workflow name */}
      <input
        className="pxa-input w-40 text-retro-xs"
        value={workflowName}
        onChange={(e) => onNameChange(e.target.value)}
        placeholder="Workflow name"
      />

      <div className="h-4 w-px bg-slate-700" />

      <PixelButton variant="ghost" size="sm" onClick={onNew}>New</PixelButton>
      <PixelButton variant="ghost" size="sm" onClick={onOpenTemplates}>Templates</PixelButton>
      <PixelButton variant="default" size="sm" onClick={onSave} disabled={status === 'saving'}>
        {status === 'saving' ? 'Saving...' : 'Save'}
      </PixelButton>

      {/* Load dropdown */}
      <div className="relative group">
        <PixelButton variant="ghost" size="sm">Load</PixelButton>
        <div className="absolute top-full left-0 mt-1 bg-slate-800 border border-slate-600 rounded shadow-lg min-w-[180px] hidden group-hover:block z-50 max-h-48 overflow-y-auto">
          {workflowList.length === 0 ? (
            <div className="px-3 py-2 text-retro-xs text-slate-500">No workflows</div>
          ) : (
            workflowList.map((w) => (
              <button
                key={w.id}
                onClick={() => onLoad(w.id)}
                className={`block w-full text-left px-3 py-1.5 text-retro-xs hover:bg-slate-700 transition-colors ${
                  w.id === currentWorkflowId ? 'text-indigo-400' : 'text-slate-300'
                }`}
              >
                {w.name}
              </button>
            ))
          )}
        </div>
      </div>

      <div className="h-4 w-px bg-slate-700" />

      <PixelButton variant="ghost" size="sm" onClick={onExport}>Export</PixelButton>
      <PixelButton variant="ghost" size="sm" onClick={handleImportClick}>Import</PixelButton>
      <input
        ref={fileInputRef}
        type="file"
        accept=".yaml,.yml"
        onChange={handleFileSelect}
        className="hidden"
      />

      <div className="h-4 w-px bg-slate-700" />

      <PixelButton
        variant="ghost"
        size="sm"
        onClick={onValidate}
        disabled={status === 'validating'}
      >
        {validationIcon} Validate
      </PixelButton>

      <PixelButton variant="success" size="sm" onClick={onRun}>
        Run
      </PixelButton>

      {/* Status indicator */}
      {status === 'loading' && (
        <span className="pixel-text text-retro-xs text-slate-500 animate-pulse">Loading...</span>
      )}
      {validationResult && !validationResult.valid && (
        <span className="pixel-text text-retro-xs text-red-400 truncate max-w-[200px]">
          {validationResult.errors[0]}
        </span>
      )}

      <div className="flex-1" />

      <PixelButton variant="ghost" size="sm" onClick={onClose}>
        ✕ Close
      </PixelButton>
    </div>
  );
}
