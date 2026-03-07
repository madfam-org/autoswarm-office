'use client';

import { useState, useCallback, useEffect } from 'react';
import type { AvatarConfig } from '@autoswarm/shared-types';
import {
  SKIN_TONES,
  HAIR_COLORS,
  OUTFIT_COLORS,
  HAIR_STYLE_NAMES,
  ACCESSORY_NAMES,
} from '@autoswarm/shared-types';
import { useFocusTrap } from '@/hooks/useFocusTrap';

interface AvatarEditorProps {
  open: boolean;
  initialConfig: AvatarConfig;
  onSave: (config: AvatarConfig) => void;
  onClose: () => void;
}

function ColorSwatch({
  color,
  selected,
  onClick,
  label,
}: {
  color: string;
  selected: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={`h-8 w-8 rounded border-2 transition-transform ${
        selected ? 'border-white scale-110' : 'border-slate-600 hover:border-slate-400'
      }`}
      style={{ backgroundColor: color }}
    />
  );
}

function OptionButton({
  label,
  selected,
  onClick,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded px-3 py-1 text-xs transition-colors ${
        selected
          ? 'bg-indigo-600 text-white'
          : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
      }`}
    >
      {label}
    </button>
  );
}

export function AvatarEditor({ open, initialConfig, onSave, onClose }: AvatarEditorProps) {
  const [config, setConfig] = useState<AvatarConfig>(initialConfig);
  const trapRef = useFocusTrap<HTMLDivElement>(open);

  const update = useCallback((partial: Partial<AvatarConfig>) => {
    setConfig((prev) => ({ ...prev, ...partial }));
  }, []);

  const handleSave = useCallback(() => {
    onSave(config);
  }, [config, onSave]);

  // Escape to close
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="absolute inset-0 z-modal flex items-center justify-center bg-black/70" role="dialog" aria-modal="true" aria-label="Avatar editor">
      <div ref={trapRef} className="w-96 rounded-lg border border-slate-700 bg-slate-900 p-6 shadow-xl">
        <h2 className="mb-4 text-center text-sm font-bold text-slate-200">
          CUSTOMIZE YOUR AVATAR
        </h2>

        {/* Preview */}
        <div className="mb-4 flex justify-center">
          <div
            className="flex h-20 w-20 items-center justify-center rounded-lg border border-slate-700"
            style={{ backgroundColor: SKIN_TONES[config.skinTone] ?? SKIN_TONES[0] }}
          >
            <div className="text-center text-[10px] text-slate-800">
              <div>
                {config.hairStyle >= 0 ? HAIR_STYLE_NAMES[config.hairStyle] : 'Bald'}
              </div>
              <div>
                {ACCESSORY_NAMES[config.accessory + 1]}
              </div>
            </div>
          </div>
        </div>

        {/* Skin Tone */}
        <div className="mb-3">
          <label className="mb-1 block text-xs text-slate-400">Skin Tone</label>
          <div className="flex gap-2">
            {SKIN_TONES.map((color, i) => (
              <ColorSwatch
                key={color}
                color={color}
                selected={config.skinTone === i}
                onClick={() => update({ skinTone: i })}
                label={`Skin tone ${i + 1}`}
              />
            ))}
          </div>
        </div>

        {/* Hair Style */}
        <div className="mb-3">
          <label className="mb-1 block text-xs text-slate-400">Hair Style</label>
          <div className="flex flex-wrap gap-1">
            <OptionButton
              label="Bald"
              selected={config.hairStyle === -1}
              onClick={() => update({ hairStyle: -1 })}
            />
            {HAIR_STYLE_NAMES.map((name, i) => (
              <OptionButton
                key={name}
                label={name}
                selected={config.hairStyle === i}
                onClick={() => update({ hairStyle: i })}
              />
            ))}
          </div>
        </div>

        {/* Hair Color */}
        {config.hairStyle >= 0 && (
          <div className="mb-3">
            <label className="mb-1 block text-xs text-slate-400">Hair Color</label>
            <div className="flex gap-2">
              {HAIR_COLORS.map((color, i) => (
                <ColorSwatch
                  key={color}
                  color={color}
                  selected={config.hairColor === i}
                  onClick={() => update({ hairColor: i })}
                  label={`Hair color ${i + 1}`}
                />
              ))}
            </div>
          </div>
        )}

        {/* Outfit Color */}
        <div className="mb-3">
          <label className="mb-1 block text-xs text-slate-400">Outfit Color</label>
          <div className="flex gap-2">
            {OUTFIT_COLORS.map((color, i) => (
              <ColorSwatch
                key={color}
                color={color}
                selected={config.outfitColor === i}
                onClick={() => update({ outfitColor: i })}
                label={`Outfit color ${i + 1}`}
              />
            ))}
          </div>
        </div>

        {/* Accessory */}
        <div className="mb-4">
          <label className="mb-1 block text-xs text-slate-400">Accessory</label>
          <div className="flex flex-wrap gap-1">
            {ACCESSORY_NAMES.map((name, i) => (
              <OptionButton
                key={name}
                label={name}
                selected={config.accessory === i - 1}
                onClick={() => update({ accessory: i - 1 })}
              />
            ))}
          </div>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded bg-slate-700 px-4 py-2 text-xs text-slate-300 hover:bg-slate-600"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="rounded bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
