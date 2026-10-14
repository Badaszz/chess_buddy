export type Mood = "normal" | "impressed" | "inaccuracy" | "blunder";

export interface AvatarPack {
  id: string;
  kind: "emoji" | "image";      // add "lottie" | "rive" later
  states: Record<Mood, string>; // emoji, or image URLs when kind === "image"
}

export const AVATAR_PACK: AvatarPack = {
  id: "emoji-default",
  kind: "emoji",
  states: { normal: "🙂", impressed: "😲", inaccuracy: "😑", blunder: "😬" },
};