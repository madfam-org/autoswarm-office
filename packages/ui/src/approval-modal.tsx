import { useState, type FC } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import type { ApprovalRequest } from '@autoswarm/shared-types';
import { Button } from './button';
import { cn } from './utils';

export interface ApprovalModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  request: ApprovalRequest;
  onApprove: (requestId: string, feedback: string) => void;
  onDeny: (requestId: string, feedback: string) => void;
}

const urgencyColors: Record<ApprovalRequest['urgency'], string> = {
  low: 'text-slate-400 bg-slate-800',
  medium: 'text-amber-300 bg-amber-900/40',
  high: 'text-orange-300 bg-orange-900/40',
  critical: 'text-red-300 bg-red-900/40 animate-pulse',
};

export const ApprovalModal: FC<ApprovalModalProps> = ({
  open,
  onOpenChange,
  request,
  onApprove,
  onDeny,
}) => {
  const [feedback, setFeedback] = useState('');

  const handleApprove = () => {
    onApprove(request.id, feedback);
    setFeedback('');
  };

  const handleDeny = () => {
    onDeny(request.id, feedback);
    setFeedback('');
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm" />
        <Dialog.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2',
            'w-full max-w-xl',
            'bg-slate-900 text-slate-100',
            'shadow-[0_0_0_3px_#000,_0_0_0_5px_#6366f1,_inset_0_0_0_1px_rgba(255,255,255,0.1)]',
            'p-6 font-mono',
            'max-h-[85vh] overflow-y-auto',
            'focus:outline-none',
          )}
        >
          <Dialog.Title className="mb-1 text-lg font-bold uppercase tracking-widest text-indigo-300">
            Approval Required
          </Dialog.Title>

          <Dialog.Description className="mb-4 text-sm text-slate-400">
            An agent is requesting permission to perform an action.
          </Dialog.Description>

          {/* Agent & Action Info */}
          <div className="mb-4 space-y-2 border border-slate-700 bg-slate-800/50 p-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Agent</span>
              <span className="font-bold text-white">{request.agentName}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Action</span>
              <span className="font-bold text-cyan-300">
                {request.actionCategory} / {request.actionType}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Urgency</span>
              <span
                className={cn(
                  'rounded px-2 py-0.5 text-xs font-bold uppercase',
                  urgencyColors[request.urgency],
                )}
              >
                {request.urgency}
              </span>
            </div>
          </div>

          {/* Reasoning */}
          <div className="mb-4">
            <h3 className="mb-1 text-xs font-bold uppercase tracking-wider text-slate-400">
              Reasoning
            </h3>
            <p className="border-l-2 border-indigo-500 bg-slate-800/50 p-3 text-sm leading-relaxed text-slate-200">
              {request.reasoning}
            </p>
          </div>

          {/* Diff block */}
          {request.diff && (
            <div className="mb-4">
              <h3 className="mb-1 text-xs font-bold uppercase tracking-wider text-slate-400">
                Diff
              </h3>
              <pre className="max-h-48 overflow-auto bg-black p-3 text-xs leading-relaxed">
                <code className="text-green-300">{request.diff}</code>
              </pre>
            </div>
          )}

          {/* Feedback */}
          <div className="mb-4">
            <label
              htmlFor="approval-feedback"
              className="mb-1 block text-xs font-bold uppercase tracking-wider text-slate-400"
            >
              Feedback (optional)
            </label>
            <textarea
              id="approval-feedback"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Add notes for the agent..."
              rows={3}
              className={cn(
                'w-full resize-none bg-slate-800 p-3 text-sm text-slate-100',
                'border border-slate-600 font-mono',
                'placeholder:text-slate-500',
                'focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500',
              )}
            />
          </div>

          {/* Actions */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">
              A = Approve | B = Deny
            </span>
            <div className="flex gap-3">
              <Button variant="deny" size="sm" onClick={handleDeny}>
                Deny
              </Button>
              <Button variant="approve" size="sm" onClick={handleApprove}>
                Approve
              </Button>
            </div>
          </div>

          <Dialog.Close asChild>
            <button
              className="absolute right-3 top-3 text-slate-500 hover:text-white focus:outline-none"
              aria-label="Close"
            >
              X
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
