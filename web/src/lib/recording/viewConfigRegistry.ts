export type ConfigField = {
  key: string;
  label: string;
  type: 'topic' | 'boolean' | 'number';
  sources?: ViewConfigSource[];
  filter?: (topic: string) => boolean;
};

export type ViewConfigSource = 'ros' | 'dataset';

export type ViewConfigDefinition = {
  type: string;
  label: string;
  description?: string;
  sources?: ViewConfigSource[];
  fields?: ConfigField[];
  defaultConfig?: (topics: string[], source?: ViewConfigSource) => Record<string, unknown>;
};

const firstMatch = (topics: string[], filter: (topic: string) => boolean) =>
  topics.find(filter) ?? '';

const cameraFilter = (topic: string) => topic.endsWith('/compressed') || !topic.includes('/');
const jointFilter = (topic: string) => topic.includes('joint_states');
const statusFilter = (topic: string) => topic.includes('status') || topic.includes('client');

export const viewConfigRegistry: ViewConfigDefinition[] = [
  {
    type: 'placeholder',
    label: 'Empty'
  },
  {
    type: 'camera',
    label: 'Camera',
    description: 'Compressed image preview',
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
        label: 'Start with Velocity',
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
    sources: ['ros']
  },
  {
    type: 'controls',
    label: 'Controls',
    description: 'Recording actions',
    sources: ['ros']
  },
  {
    type: 'progress',
    label: 'Progress',
    description: 'Episode progress',
    sources: ['ros']
  },
  {
    type: 'timeline',
    label: 'Timeline',
    description: 'Recording timeline',
    sources: ['ros', 'dataset']
  },
  {
    type: 'devices',
    label: 'Devices',
    description: 'Camera/arm status',
    sources: ['ros']
  },
  {
    type: 'settings',
    label: 'Settings',
    description: 'Inference/recording runtime settings',
    sources: ['ros']
  }
];

export const getViewConfigDefinition = (type: string) =>
  viewConfigRegistry.find((view) => view.type === type);

export const getViewConfigOptions = () => viewConfigRegistry.filter((view) => view.type !== 'placeholder');

export const getViewConfigOptionsBySource = (source: ViewConfigSource) =>
  getViewConfigOptions().filter((view) => !view.sources || view.sources.includes(source));

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
