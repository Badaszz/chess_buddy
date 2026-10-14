import { AVATAR_PACK, type Mood } from "@/lib/avatarPack";

export function CoachAvatar({ mood, size = 48 }: { mood: string; size?: number }) {
  const state: Mood = mood in AVATAR_PACK.states ? (mood as Mood) : "normal";   // unknown -> normal
  const label = `Coach looks ${state === "normal" ? "calm" : state}`;
  const asset = AVATAR_PACK.states[state];
  return (
    <div key={state} role="img" aria-label={label} className="avatar-pop inline-flex items-center justify-center"
         style={{ width: size, height: size, fontSize: size * 0.8 }}>
      {AVATAR_PACK.kind === "image" ? <img src={asset} alt="" width={size} height={size} /> : <span>{asset}</span>}
    </div>
  );
}