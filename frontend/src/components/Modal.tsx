import type { ReactNode } from "react";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** Extra class on the dialog, e.g. `modal-wide` for a chart. */
  className?: string;
}

/** Simple centred dialog. */
export function Modal({ open, title, onClose, children, footer, className }: ModalProps) {
  if (!open) {
    return null;
  }
  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className={className ? "modal " + className : "modal"}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <div className="row-between">
          <h3>{title}</h3>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Kapat
          </button>
        </div>
        {children}
        {footer && <div className="btn-row">{footer}</div>}
      </div>
    </div>
  );
}
