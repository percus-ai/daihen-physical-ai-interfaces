export type ListFilterOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

export type ListFilterTextField = {
  type: 'text';
  key: string;
  label: string;
  placeholder?: string;
};

export type ListFilterSelectField = {
  type: 'select';
  key: string;
  label: string;
  options: ListFilterOption[];
};

export type ListFilterField = ListFilterTextField | ListFilterSelectField;

export const resolveFilterValues = (
  fields: ListFilterField[],
  values: Record<string, string>,
  defaults: Record<string, string>
): Record<string, string> => {
  const resolved: Record<string, string> = {};
  for (const field of fields) {
    resolved[field.key] = values[field.key] ?? defaults[field.key] ?? '';
  }
  return resolved;
};
