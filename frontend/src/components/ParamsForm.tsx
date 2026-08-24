import { Toggle } from "@/components/Toggle";
import type { JsonSchema, JsonSchemaProperty } from "@/types/api";
import { titleCase } from "@/utils/format";

interface ParamsFormProps {
  schema: JsonSchema;
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  disabled?: boolean;
}

function resolveType(property: JsonSchemaProperty): string {
  if (property.type) {
    return property.type;
  }
  const first = property.anyOf?.find((item) => item.type && item.type !== "null");
  return first?.type ?? "string";
}

/**
 * Renders a settings form directly from the Pydantic JSON schema exposed by
 * the backend. Adding a parameter to a strategy automatically adds a field
 * here, with no frontend change.
 */
export function ParamsForm({ schema, values, onChange, disabled = false }: ParamsFormProps) {
  const properties = schema.properties ?? {};
  const keys = Object.keys(properties);

  if (keys.length === 0) {
    return <div className="table-empty">This strategy has no configurable parameters.</div>;
  }

  return (
    <div className="grid grid-3">
      {keys.map((key) => {
        const property = properties[key];
        const type = resolveType(property);
        const label = property.title ?? titleCase(key);
        const current = values[key] ?? property.default;

        if (type === "boolean") {
          return (
            <div className="field" key={key}>
              <label>{label}</label>
              <Toggle
                checked={Boolean(current)}
                disabled={disabled}
                onChange={(value) => onChange(key, value)}
              />
              {property.description && <small>{property.description}</small>}
            </div>
          );
        }

        if (type === "integer" || type === "number") {
          const step = type === "integer" ? 1 : 0.01;
          return (
            <div className="field" key={key}>
              <label htmlFor={key}>{label}</label>
              <input
                id={key}
                type="number"
                step={step}
                min={property.minimum ?? property.exclusiveMinimum}
                max={property.maximum ?? property.exclusiveMaximum}
                disabled={disabled}
                value={current === undefined || current === null ? "" : String(current)}
                onChange={(event) =>
                  onChange(
                    key,
                    event.target.value === ""
                      ? null
                      : type === "integer"
                        ? Number.parseInt(event.target.value, 10)
                        : Number.parseFloat(event.target.value),
                  )
                }
              />
              {property.description && <small>{property.description}</small>}
            </div>
          );
        }

        return (
          <div className="field" key={key}>
            <label htmlFor={key}>{label}</label>
            <input
              id={key}
              type="text"
              disabled={disabled}
              value={current === undefined || current === null ? "" : String(current)}
              onChange={(event) => onChange(key, event.target.value)}
            />
            {property.description && <small>{property.description}</small>}
          </div>
        );
      })}
    </div>
  );
}
