import type { ReactNode } from "react";

interface PanelProps {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** Card container used by every page section. */
export function Panel({ title, subtitle, actions, children, className }: PanelProps) {
  return (
    <section className={className ? "panel " + className : "panel"}>
      {(title || actions) && (
        <header className="panel-header">
          <div>
            {title && <div className="panel-title">{title}</div>}
            {subtitle && <div className="panel-subtitle">{subtitle}</div>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}
