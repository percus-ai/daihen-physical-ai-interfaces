export type BundledTorchDefaults = {
  pytorch_version: string;
  torchvision_version: string;
};

export type SystemSettings = {
  bundled_torch: BundledTorchDefaults;
  updated_at?: string | null;
};

export type HuggingFaceSecretStatus = {
  has_token: boolean;
  token_preview?: string | null;
  updated_at?: string | null;
};

export type UserSettings = {
  user_id: string;
  huggingface: HuggingFaceSecretStatus;
};
