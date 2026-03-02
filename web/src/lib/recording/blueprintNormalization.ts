import type { BlueprintNode } from '$lib/recording/blueprint';
import { getViewConfigDefinition, type ViewConfigSource } from '$lib/recording/viewConfigRegistry';

export type BlueprintNormalizeEnv = {
  source: ViewConfigSource;
  topics: string[];
  datasetCameraKeys?: string[];
  datasetSignalKeys?: string[];
};

const hasOwn = (obj: Record<string, unknown>, key: string) => Object.prototype.hasOwnProperty.call(obj, key);

export const fillDefaultConfig = (node: BlueprintNode, topics: string[], source: ViewConfigSource): BlueprintNode => {
  if (node.type === 'view') {
    const definition = getViewConfigDefinition(node.viewType);
    if (!definition?.defaultConfig) return node;
    const defaults = definition.defaultConfig(topics, source);
    const nextConfig = { ...defaults, ...node.config };

    let changed = false;
    for (const key of Object.keys(defaults)) {
      if (!hasOwn(node.config, key)) {
        changed = true;
        break;
      }
    }
    return changed ? { ...node, config: nextConfig } : node;
  }

  if (node.type === 'split') {
    const left = fillDefaultConfig(node.children[0], topics, source);
    const right = fillDefaultConfig(node.children[1], topics, source);
    if (left === node.children[0] && right === node.children[1]) return node;
    return { ...node, children: [left, right] };
  }

  const nextTabs = node.tabs.map((tab) => {
    const child = fillDefaultConfig(tab.child, topics, source);
    return child === tab.child ? tab : { ...tab, child };
  });
  const changed = nextTabs.some((tab, idx) => tab !== node.tabs[idx]);
  return changed ? { ...node, tabs: nextTabs } : node;
};

export const ensureDatasetCameraTopics = (node: BlueprintNode, keys: string[], used = new Set<string>()): BlueprintNode => {
  if (!keys.length) return node;

  if (node.type === 'view' && node.viewType === 'camera') {
    const topic = typeof node.config?.topic === 'string' ? node.config.topic.trim() : '';
    if (topic && keys.includes(topic)) {
      used.add(topic);
      return node;
    }

    const fallback = keys.find((key) => !used.has(key)) ?? keys[0] ?? '';
    if (!fallback) return node;

    used.add(fallback);
    return {
      ...node,
      config: {
        ...node.config,
        topic: fallback
      }
    };
  }

  if (node.type === 'split') {
    const left = ensureDatasetCameraTopics(node.children[0], keys, used);
    const right = ensureDatasetCameraTopics(node.children[1], keys, used);
    if (left === node.children[0] && right === node.children[1]) return node;
    return { ...node, children: [left, right] };
  }

  if (node.type !== 'tabs') return node;
  const nextTabs = node.tabs.map((tab) => {
    const child = ensureDatasetCameraTopics(tab.child, keys, used);
    return child === tab.child ? tab : { ...tab, child };
  });
  const changed = nextTabs.some((tab, idx) => tab !== node.tabs[idx]);
  return changed ? { ...node, tabs: nextTabs } : node;
};

export const ensureDatasetJointTopics = (node: BlueprintNode, keys: string[]): BlueprintNode => {
  if (!keys.length) return node;
  const resolvedFallback = keys.includes('observation.state') ? 'observation.state' : keys[0] ?? '';
  if (!resolvedFallback) return node;

  if (node.type === 'view' && node.viewType === 'joint_state') {
    const topic = typeof node.config?.topic === 'string' ? node.config.topic.trim() : '';
    if (topic && keys.includes(topic)) return node;
    return {
      ...node,
      config: {
        ...node.config,
        topic: resolvedFallback
      }
    };
  }

  if (node.type === 'split') {
    const left = ensureDatasetJointTopics(node.children[0], keys);
    const right = ensureDatasetJointTopics(node.children[1], keys);
    if (left === node.children[0] && right === node.children[1]) return node;
    return { ...node, children: [left, right] };
  }

  if (node.type !== 'tabs') return node;
  const nextTabs = node.tabs.map((tab) => {
    const child = ensureDatasetJointTopics(tab.child, keys);
    return child === tab.child ? tab : { ...tab, child };
  });
  const changed = nextTabs.some((tab, idx) => tab !== node.tabs[idx]);
  return changed ? { ...node, tabs: nextTabs } : node;
};

export const normalizeBlueprint = (blueprint: BlueprintNode, env: BlueprintNormalizeEnv): BlueprintNode => {
  if (env.source !== 'dataset') {
    return fillDefaultConfig(blueprint, env.topics, env.source);
  }

  const cameraKeys = env.datasetCameraKeys ?? [];
  const signalKeys = env.datasetSignalKeys ?? [];

  // Match the runtime behavior: for dataset mode, fill missing dataset topics first,
  // then apply default configs so defaults don't force all camera views to the same topic.
  const withCameraTopics = cameraKeys.length ? ensureDatasetCameraTopics(blueprint, cameraKeys) : blueprint;
  const withJointTopics = signalKeys.length ? ensureDatasetJointTopics(withCameraTopics, signalKeys) : withCameraTopics;
  return fillDefaultConfig(withJointTopics, env.topics, env.source);
};
