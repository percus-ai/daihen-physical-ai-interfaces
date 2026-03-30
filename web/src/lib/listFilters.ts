export type ListFilterOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

type ListFilterBaseField = {
  label: string;
  section?: string;
};

export type ListFilterTextField = ListFilterBaseField & {
  type: 'text';
  key: string;
  placeholder?: string;
};

export type ListFilterSelectField = ListFilterBaseField & {
  type: 'select';
  key: string;
  options: ListFilterOption[];
};

export type ListFilterDateRangeField = ListFilterBaseField & {
  type: 'date-range';
  keyFrom: string;
  keyTo: string;
  placeholderFrom?: string;
  placeholderTo?: string;
};

export type ListFilterNumberRangeField = ListFilterBaseField & {
  type: 'number-range';
  keyMin: string;
  keyMax: string;
  placeholderMin?: string;
  placeholderMax?: string;
  min?: number;
  max?: number;
  step?: number;
};

export type ListFilterField =
  | ListFilterTextField
  | ListFilterSelectField
  | ListFilterDateRangeField
  | ListFilterNumberRangeField;

export const getFieldKeys = (field: ListFilterField): string[] => {
  if (field.type === 'text' || field.type === 'select') {
    return [field.key];
  }
  if (field.type === 'date-range') {
    return [field.keyFrom, field.keyTo];
  }
  return [field.keyMin, field.keyMax];
};

export const resolveFilterValues = (
  fields: ListFilterField[],
  values: Record<string, string>,
  defaults: Record<string, string>
): Record<string, string> => {
  const resolved: Record<string, string> = {};
  for (const field of fields) {
    for (const key of getFieldKeys(field)) {
      resolved[key] = values[key] ?? defaults[key] ?? '';
    }
  }
  return resolved;
};
