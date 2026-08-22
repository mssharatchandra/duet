import {Composition} from "remotion";
import {VoiceAiIntro} from "./VoiceAiIntro";

export const MyComposition: React.FC = () => {
  return (
    <Composition
      id="DuetVoiceAiIntro"
      component={VoiceAiIntro}
      durationInFrames={1680}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
