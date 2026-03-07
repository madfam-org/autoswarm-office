import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from './utils';

const pixelBorderBase =
  'box-shadow: 0 0 0 2px #000, inset 0 0 0 1px rgba(255,255,255,0.15)';

const buttonVariants = cva(
  [
    'inline-flex items-center justify-center gap-2',
    'font-mono text-sm font-bold uppercase tracking-wider',
    'transition-all duration-100 active:translate-y-[2px]',
    'disabled:pointer-events-none disabled:opacity-50',
    'cursor-pointer select-none',
    'outline-none focus-visible:ring-2 focus-visible:ring-offset-2',
    // 16-bit pixel border via box-shadow
    'shadow-[0_0_0_2px_#000,_inset_0_0_0_1px_rgba(255,255,255,0.15)]',
  ].join(' '),
  {
    variants: {
      variant: {
        default: [
          'bg-indigo-600 text-white',
          'hover:bg-indigo-500',
          'focus-visible:ring-indigo-400',
        ].join(' '),
        destructive: [
          'bg-red-700 text-white',
          'hover:bg-red-600',
          'focus-visible:ring-red-400',
        ].join(' '),
        outline: [
          'bg-transparent text-slate-200 border-2 border-slate-600',
          'hover:bg-slate-800 hover:text-white',
          'focus-visible:ring-slate-400',
        ].join(' '),
        ghost: [
          'bg-transparent text-slate-300 shadow-none',
          'hover:bg-slate-800 hover:text-white',
          'focus-visible:ring-slate-400',
        ].join(' '),
        approve: [
          'bg-emerald-700 text-white',
          'shadow-[0_0_0_2px_#065f46,_0_0_0_4px_#10b981,_inset_0_0_0_1px_rgba(255,255,255,0.2)]',
          'hover:bg-emerald-600',
          'focus-visible:ring-emerald-400',
        ].join(' '),
        deny: [
          'bg-red-800 text-white',
          'shadow-[0_0_0_2px_#7f1d1d,_0_0_0_4px_#ef4444,_inset_0_0_0_1px_rgba(255,255,255,0.2)]',
          'hover:bg-red-700',
          'focus-visible:ring-red-400',
        ].join(' '),
      },
      size: {
        default: 'h-10 px-5 py-2',
        xs: 'h-6 px-2 py-0.5 text-[8px]',
        sm: 'h-8 px-3 py-1 text-xs',
        lg: 'h-12 px-8 py-3 text-base',
        icon: 'h-10 w-10 p-0',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);

Button.displayName = 'Button';
