import { describe, expect, it } from 'vitest';

import { createSplitNode, createTabsNode, createViewNode, type BlueprintNode } from '$lib/recording/blueprint';
import { normalizeBlueprint } from '$lib/recording/blueprintNormalization';

describe('blueprintNormalization', () => {
  it('fills default config fields for joint_state', () => {
    const blueprint: BlueprintNode = createViewNode('joint_state', {});
    const normalized = normalizeBlueprint(blueprint, { source: 'dataset', topics: [], datasetSignalKeys: [] });
    expect(normalized.type).toBe('view');
    if (normalized.type !== 'view') return;
    expect(normalized.viewType).toBe('joint_state');
    expect(normalized.config).toMatchObject({
      showVelocity: false,
      maxPoints: 160
    });
  });

  it('assigns dataset camera topics with stable fallbacks', () => {
    const blueprint: BlueprintNode = createSplitNode(
      'row',
      createViewNode('camera', {}),
      createViewNode('camera', {}),
      [0.5, 0.5]
    );

    const normalized = normalizeBlueprint(blueprint, {
      source: 'dataset',
      topics: ['cam_top', 'cam_side'],
      datasetCameraKeys: ['cam_top', 'cam_side'],
      datasetSignalKeys: ['observation.state']
    });

    expect(normalized.type).toBe('split');
    if (normalized.type !== 'split') return;

    const left = normalized.children[0];
    const right = normalized.children[1];
    expect(left.type).toBe('view');
    expect(right.type).toBe('view');
    if (left.type !== 'view' || right.type !== 'view') return;

    expect(left.config.topic).toBe('cam_top');
    expect(right.config.topic).toBe('cam_side');
  });

  it('assigns observation.state to joint_state when available', () => {
    const blueprint: BlueprintNode = createViewNode('joint_state', {});
    const normalized = normalizeBlueprint(blueprint, {
      source: 'dataset',
      topics: [],
      datasetSignalKeys: ['foo', 'observation.state', 'bar']
    });
    expect(normalized.type).toBe('view');
    if (normalized.type !== 'view') return;
    expect(normalized.config.topic).toBe('observation.state');
  });

  it('does not overwrite an existing valid topic selection', () => {
    const blueprint: BlueprintNode = createViewNode('camera', { topic: 'cam_side' });
    const normalized = normalizeBlueprint(blueprint, {
      source: 'dataset',
      topics: ['cam_top', 'cam_side'],
      datasetCameraKeys: ['cam_top', 'cam_side']
    });
    expect(normalized.type).toBe('view');
    if (normalized.type !== 'view') return;
    expect(normalized.config.topic).toBe('cam_side');
  });

  it('walks tabs trees and normalizes children', () => {
    const blueprint: BlueprintNode = createTabsNode(
      [
        { id: 'a', title: 'A', child: createViewNode('camera', {}) },
        { id: 'b', title: 'B', child: createViewNode('joint_state', {}) }
      ],
      'a'
    );

    const normalized = normalizeBlueprint(blueprint, {
      source: 'dataset',
      topics: ['cam_top'],
      datasetCameraKeys: ['cam_top'],
      datasetSignalKeys: ['observation.state']
    });

    expect(normalized.type).toBe('tabs');
    if (normalized.type !== 'tabs') return;
    const camera = normalized.tabs[0].child;
    const joint = normalized.tabs[1].child;
    expect(camera.type).toBe('view');
    expect(joint.type).toBe('view');
    if (camera.type !== 'view' || joint.type !== 'view') return;
    expect(camera.config.topic).toBe('cam_top');
    expect(joint.config.topic).toBe('observation.state');
  });
});

