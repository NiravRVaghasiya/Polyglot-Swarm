// Learner-facing wording for the planner's structured output.
//
// The planner's `reason` is an audit explanation written for engineers
// ("no reliable evidence on gender_agreement yet (0 observation(s))"). The
// UI builds its own title and one-line description from the structured
// fields (activity type, intent, target) and keeps `reason` behind a "Why?"
// disclosure for transparency.

import type { PlanAction } from "./api";

/** "ser_vs_estar" -> "Ser vs estar"; "speaking" -> "Speaking". */
export function humanize(id: string | null | undefined): string {
  if (!id) return "";
  const words = id.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "1 observation", "3 observations". */
export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export interface ActionText {
  title: string;
  description: string;
}

/** A title and a one-line, plain-language description for a plan action. */
export function describeAction(a: PlanAction): ActionText {
  const topic = humanize(a.target);
  switch (a.type) {
    case "diagnostic_check":
      return {
        title: `Quick check: ${topic}`,
        description:
          a.intent === "assessment"
            ? "A few short questions to find your level here."
            : "Your last session here was weaker than usual. A quick check tells us whether it was a one-off.",
      };
    case "speaking_check":
      return {
        title: "Speaking check",
        description: "Say a few sentences so the tutor can place your speaking.",
      };
    case "listening_check":
      return {
        title: "Listening check",
        description: "Listen to a short clip and answer a few questions.",
      };
    case "grammar_practice":
      switch (a.intent) {
        case "remediation":
          return {
            title: `Practise: ${topic}`,
            description: "This keeps tripping you up, so we'll practise it at a level you can manage.",
          };
        case "progression":
          return {
            title: `Level up: ${topic}`,
            description: "You've got the basics. Time for harder examples.",
          };
        case "introduction":
          return { title: `New: ${topic}`, description: "Something new to learn next." };
        default:
          return {
            title: `Practise: ${topic}`,
            description: "You're getting there. A little more practice makes it stick.",
          };
      }
    case "retention_review":
      return {
        title: `Refresh: ${topic}`,
        description: "You knew this. A quick review keeps it from fading.",
      };
    case "vocabulary_review":
      return {
        title: `Review “${a.target}”`,
        description: "This word is due for review, so it sticks.",
      };
    case "vocabulary_remediation":
      return {
        title: `Practise “${a.target}”`,
        description: "This word keeps slipping. Let's lock it in.",
      };
    case "vocabulary_expansion":
      return { title: "New words", description: "Pick up a few useful new words." };
    case "writing_exercise":
      return { title: "Writing practice", description: "Write a few sentences and get feedback." };
    case "conversation_practice":
      return {
        title: "Conversation practice",
        description: "Use what you know in a real conversation.",
      };
    default:
      return { title: humanize(a.type), description: "" };
  }
}

/** Evidence status, worded for a learner. */
export function evidenceText(status: string | null | undefined): string {
  switch (status) {
    case "provisional":
      return "early estimate";
    case "estimated":
      return "estimated";
    case "validated":
      return "confirmed";
    default:
      return "not enough practice yet";
  }
}

/** Listening speed from an Edge TTS rate such as "-15%" or "+0%". */
export function speedText(rate: string): string | null {
  const n = Number.parseInt(rate, 10);
  if (Number.isNaN(n) || n === 0) return null;
  return n < 0 ? "slower speech" : "faster speech";
}
