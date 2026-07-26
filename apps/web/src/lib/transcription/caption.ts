import type { CaptionChunk } from "@/types/transcription";
import {
	DEFAULT_MAX_CHARS_PER_LINE,
	MIN_CAPTION_DURATION_SECONDS,
} from "@/constants/transcription-constants";

export interface CaptionWord {
	word: string;
	start: number;
	end: number;
}

export interface CaptionSourceSegment {
	text: string;
	start: number;
	end: number;
	words?: CaptionWord[];
}

interface TokenEntry {
	text: string;
	word?: CaptionWord;
}

function splitLongToken(token: string, maxLen: number): string[] {
	if (token.length <= maxLen) return [token];
	const pieces: string[] = [];
	for (let i = 0; i < token.length; i += maxLen) {
		pieces.push(token.slice(i, i + maxLen));
	}
	return pieces;
}

function buildTokenEntries(
	segment: CaptionSourceSegment,
	maxCharsPerLine: number,
): TokenEntry[] {
	if (segment.words && segment.words.length > 0) {
		const entries: TokenEntry[] = [];
		for (const w of segment.words) {
			const pieces = splitLongToken(w.word, maxCharsPerLine);
			if (pieces.length === 1) {
				entries.push({ text: w.word, word: w });
				continue;
			}
			const wordDuration = w.end - w.start;
			const totalLen = w.word.length;
			let consumed = 0;
			for (const piece of pieces) {
				const pieceStart = w.start + (consumed / totalLen) * wordDuration;
				consumed += piece.length;
				const pieceEnd = w.start + (consumed / totalLen) * wordDuration;
				entries.push({
					text: piece,
					word: { word: piece, start: pieceStart, end: pieceEnd },
				});
			}
		}
		return entries;
	}

	const rawTokens = segment.text.trim().split(/\s+/).filter(Boolean);
	const entries: TokenEntry[] = [];
	for (const token of rawTokens) {
		for (const piece of splitLongToken(token, maxCharsPerLine)) {
			entries.push({ text: piece });
		}
	}
	return entries;
}

function groupEntries(
	entries: TokenEntry[],
	maxCharsPerLine: number,
): TokenEntry[][] {
	const groups: TokenEntry[][] = [];
	let current: TokenEntry[] = [];
	let currentLen = 0;

	for (const entry of entries) {
		const addedLen =
			current.length === 0
				? entry.text.length
				: currentLen + 1 + entry.text.length;

		if (current.length > 0 && addedLen > maxCharsPerLine) {
			groups.push(current);
			current = [entry];
			currentLen = entry.text.length;
		} else {
			current.push(entry);
			currentLen = addedLen;
		}
	}

	if (current.length > 0) groups.push(current);
	return groups;
}

export function buildCaptionChunks({
	segments,
	maxCharsPerLine = DEFAULT_MAX_CHARS_PER_LINE,
	minDuration = MIN_CAPTION_DURATION_SECONDS,
}: {
	segments: CaptionSourceSegment[];
	maxCharsPerLine?: number;
	minDuration?: number;
}): CaptionChunk[] {
	const chunks: CaptionChunk[] = [];
	let globalEndTime = 0;

	for (const segment of segments) {
		if (!segment.text.trim()) continue;

		const entries = buildTokenEntries(segment, maxCharsPerLine);
		if (entries.length === 0) continue;

		const groups = groupEntries(entries, maxCharsPerLine);
		const hasWordTimings = entries.every((e) => e.word !== undefined);

		if (hasWordTimings) {
			for (const group of groups) {
				const words = group.map((e) => e.word as CaptionWord);
				const text = group.map((e) => e.text).join(" ");
				const rawStart = words[0].start;
				const rawEnd = words[words.length - 1].end;
				const start = Math.max(rawStart, globalEndTime);
				const end = Math.max(rawEnd, start + minDuration);

				chunks.push({ text, startTime: start, duration: end - start, words });
				globalEndTime = end;
			}
		} else {
			const segmentDuration = segment.end - segment.start;
			const totalChars = groups.reduce(
				(sum, group) => sum + group.map((e) => e.text).join(" ").length,
				0,
			);
			const charsPerSecond = totalChars / segmentDuration;
			let cursor = Math.max(segment.start, globalEndTime);

			for (const group of groups) {
				const text = group.map((e) => e.text).join(" ");
				const rawDuration = text.length / charsPerSecond;
				const duration = Math.max(minDuration, rawDuration);

				chunks.push({ text, startTime: cursor, duration });
				cursor += duration;
				globalEndTime = cursor;
			}
		}
	}

	return chunks;
}
