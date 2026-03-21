// Text wrapping utility for SVG node labels.
// Breaks text on word boundaries and caps output at 3 lines with ellipsis.

/**
 * Wrap text into multiple lines, breaking on spaces.
 * Returns at most 3 lines; the last line is truncated with an ellipsis
 * if the text overflows.
 */
export function wrapText(text: string, maxCharsPerLine: number): string[] {
  if (text.length <= maxCharsPerLine) return [text]

  const words = text.split(' ')
  const lines: string[] = []
  let currentLine = ''

  for (const word of words) {
    if (currentLine.length === 0) {
      currentLine = word
    } else if (currentLine.length + 1 + word.length <= maxCharsPerLine) {
      currentLine += ' ' + word
    } else {
      lines.push(currentLine)
      currentLine = word
    }
  }
  if (currentLine) lines.push(currentLine)

  // Limit to 3 lines max, truncate last line if needed
  if (lines.length > 3) {
    lines.length = 3
    lines[2] = lines[2].slice(0, maxCharsPerLine - 1) + '\u2026'
  }

  return lines
}
