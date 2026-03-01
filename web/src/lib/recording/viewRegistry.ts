import type { Component } from 'svelte';
import CameraView from '$lib/components/recording/views/CameraView.svelte';
import JointStateView from '$lib/components/recording/views/JointStateView.svelte';
import StatusView from '$lib/components/recording/views/StatusView.svelte';
import TopicsView from '$lib/components/recording/views/TopicsView.svelte';
import ControlsView from '$lib/components/recording/views/ControlsView.svelte';
import ProgressView from '$lib/components/recording/views/ProgressView.svelte';
import TimelineView from '$lib/components/recording/views/TimelineView.svelte';
import DevicesView from '$lib/components/recording/views/DevicesView.svelte';
import SettingsView from '$lib/components/recording/views/SettingsView.svelte';
import PlaceholderView from '$lib/components/recording/views/PlaceholderView.svelte';

export type ConfigField = {
  key: string;
  label: string;
  type: 'topic' | 'boolean' | 'number';
  sources?: ViewConfigSource[];
  filter?: (topic: string) => boolean;
};

export type ViewConfigSource = 'ros' | 'dataset';

export type ViewTypeDefinition = {
  type: string;
  label: string;
  description?: string;
  component: Component<any>;
  sources?: ViewConfigSource[];
  fields?: ConfigField[];
  defaultConfig?: (topics: string[], source?: ViewConfigSource) => Record<string, unknown>;
};

const firstMatch = (topics: string[], filter: (topic: string) => boolean) =>
  topics.find(filter) ?? '';

const cameraFilter = (topic: string) => topic.endsWith('/compressed') || !topic.includes('/');
const jointFilter = (topic: string) => topic.includes('joint_states');
const statusFilter = (topic: string) => topic.includes('status') || topic.includes('client');

export const viewRegistry: ViewTypeDefinition[] = [
  {
    type: 'placeholder',
    label: 'Empty',
    component: PlaceholderView
  },
  {
    type: 'camera',
    label: 'Camera',
    description: 'Compressed image preview',
    component: CameraView,
    sources: ['ros', 'dataset'],
    fields: [
      {
        key: 'topic',
        label: 'Topic',
        type: 'topic',
        sources: ['ros'],
        filter: cameraFilter
      },
      {
        key: 'topic',
        label: 'Camera',
        type: 'topic',
        sources: ['dataset']
      }
    ],
    defaultConfig: (topics, source = 'ros') => ({
      topic: source === 'dataset' ? topics[0] ?? '' : firstMatch(topics, cameraFilter)
    })
  },
  {
    type: 'joint_state',
    label: 'Joint State',
    description: 'Joint state timeseries',
    component: JointStateView,
    fields: [
      {
        key: 'topic',
        label: 'Topic',
        type: 'topic',
        sources: ['ros'],
        filter: jointFilter
      },
      {
        key: 'topic',
        label: 'Signal',
        type: 'topic',
        sources: ['dataset']
      },
      {
        key: 'showVelocity',
        label: 'Show velocity',
        type: 'boolean'
      },
      {
        key: 'maxPoints',
        label: 'Max points',
        type: 'number'
      }
    ],
    defaultConfig: (topics, source = 'ros') => ({
      topic: source === 'ros' ? firstMatch(topics, jointFilter) : '',
      showVelocity: false,
      maxPoints: 160
    })
  },
  {
    type: 'status',
    label: 'Status',
    description: 'Key-value status',
    component: StatusView,
    sources: ['ros'],
    fields: [
      {
        key: 'topic',
        label: 'Topic',
        type: 'topic',
        sources: ['ros'],
        filter: statusFilter
      }
    ],
    defaultConfig: (topics, source = 'ros') => ({
      topic:
        source === 'ros'
          ? firstMatch(topics, (t) => t.includes('lerobot_recorder/status')) || firstMatch(topics, statusFilter)
          : ''
    })
  },
  {
    type: 'topics',
    label: 'Topics',
    description: 'Topic list',
    component: TopicsView,
    sources: ['ros']
  },
  {
    type: 'controls',
    label: 'Controls',
    description: 'Recording actions',
    component: ControlsView,
    sources: ['ros']
  },
  {
    type: 'progress',
    label: 'Progress',
    description: 'Episode progress',
    component: ProgressView,
    sources: ['ros']
  },
  {
    type: 'timeline',
    label: 'Timeline',
    description: 'Recording timeline',
    component: TimelineView,
    sources: ['ros', 'dataset']
  },
  {
    type: 'devices',
    label: 'Devices',
    description: 'Camera/arm status',
    component: DevicesView,
    sources: ['ros']
  },
  {
    type: 'settings',
    label: 'Settings',
    description: 'Inference/recording runtime settings',
    component: SettingsView,
    sources: ['ros']
  }
];

export const getViewDefinition = (type: string) => viewRegistry.find((view) => view.type === type);

export const getViewOptions = () => viewRegistry.filter((view) => view.type !== 'placeholder');

export const getViewOptionsBySource = (source: ViewConfigSource) =>
  getViewOptions().filter((view) => !view.sources || view.sources.includes(source));

export const isFieldSupported = (field: ConfigField, source: ViewConfigSource): boolean =>
  !field.sources || field.sources.includes(source);

export const getTopicFieldOptions = (
  field: ConfigField,
  topics: string[],
  source: ViewConfigSource
): string[] => {
  if (field.type !== 'topic') return [];
  if (!isFieldSupported(field, source)) return [];
  return topics.filter((topic) => field.filter?.(topic) ?? true);
};
