import { scriptedMissionEvents } from './fake-data';
import type { MissionEvent } from './types';

export function parseDroneImageToMissionEvent(imageRef: string): MissionEvent {
  const fakeDroneEvent = scriptedMissionEvents.find(
    (event) => event.eventType === 'visual_observation'
  );
  if (!fakeDroneEvent) {
    throw new Error('Fake drone event is missing from scripted mission data.');
  }

  return {
    ...fakeDroneEvent,
    rawInput: {
      modality: 'image',
      contentRef: imageRef,
    },
  };

  // TODO(Unsiloed/Qwen): upload image bytes or content reference.
  // TODO(Unsiloed/Qwen): parse the visual scene into structured JSON.
  // TODO(Unsiloed/Qwen): normalize parser output into MissionEvent.
  // TODO(Unsiloed/Qwen): store the MissionEvent in Moss/dynamic memory.
  // TODO(Unsiloed/Qwen): apply the MissionEvent to WorldState.
}
