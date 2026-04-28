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
  features_repo: FeaturesRepoSettings;
  updated_at?: string | null;
};

export type HuggingFaceSecretStatus = {
  has_token: boolean;
  token?: string | null;
  updated_at?: string | null;
};

export type UserProfileSettings = {
  username?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  updated_at?: string | null;
};

export type UserSettings = {
  user_id: string;
  profile: UserProfileSettings;
  huggingface: HuggingFaceSecretStatus;
};
