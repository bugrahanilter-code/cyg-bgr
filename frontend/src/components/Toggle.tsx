interface ToggleProps {
  checked: boolean;
  onChange: (value: boolean) => void;
  label?: string;
  disabled?: boolean;
}

/** Accessible on/off switch. */
export function Toggle({ checked, onChange, label, disabled = false }: ToggleProps) {
  return (
    <label className="toggle" style={{ opacity: disabled ? 0.5 : 1 }}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        style={{ position: "absolute", opacity: 0, width: 0, height: 0 }}
      />
      <span className={checked ? "toggle-track on" : "toggle-track"}>
        <span className="toggle-thumb" />
      </span>
      {label && <span className="small">{label}</span>}
    </label>
  );
}
