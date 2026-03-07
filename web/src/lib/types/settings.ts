export type BundledTorchDefaults = {
  pytorch_version: string;
  torchvision_version: string;
};

export type FeaturesRepoSettings = {
  repo_url: string;
  repo_ref: string;
  repo_commit?: string | null;
};

export type FeaturesRepoCommitSuggestion = {
  sha: string;
  short_sha: string;
  message: string;
};

export type FeaturesRepoSuggestions = {
  repo_url: string;
  repo_ref?: string | null;
  default_branch?: string | null;
  branches: string[];
  commits: FeaturesRepoCommitSuggestion[];
};

export type SystemSettings = {
  bundled_torch: BundledTorchDefaults;
  features_repo: FeaturesRepoSettings;
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
