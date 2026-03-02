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

import {
  getTopicFieldOptions,
  getViewConfigDefinition,
  getViewConfigOptions,
  getViewConfigOptionsBySource,
  isFieldSupported,
  viewConfigRegistry,
  type ConfigField,
  type ViewConfigDefinition,
  type ViewConfigSource
} from '$lib/recording/viewConfigRegistry';

export { getTopicFieldOptions, isFieldSupported, type ConfigField, type ViewConfigSource };

export type ViewTypeDefinition = ViewConfigDefinition & {
  component: Component<any>;
};

const componentsByType: Record<string, Component<any>> = {
  placeholder: PlaceholderView,
  camera: CameraView,
  joint_state: JointStateView,
  status: StatusView,
  topics: TopicsView,
  controls: ControlsView,
  progress: ProgressView,
  timeline: TimelineView,
  devices: DevicesView,
  settings: SettingsView
};

export const viewRegistry: ViewTypeDefinition[] = viewConfigRegistry.map((view) => ({
  ...view,
  component: componentsByType[view.type] ?? PlaceholderView
}));

export const getViewDefinition = (type: string) => viewRegistry.find((view) => view.type === type);

export const getViewOptions = () => getViewConfigOptions().map((view) => getViewDefinition(view.type)!).filter(Boolean);

export const getViewOptionsBySource = (source: ViewConfigSource) =>
  getViewConfigOptionsBySource(source).map((view) => getViewDefinition(view.type)!).filter(Boolean);

export const getViewConfig = getViewConfigDefinition;
