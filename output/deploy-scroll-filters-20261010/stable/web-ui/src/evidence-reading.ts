/** Split only short, explicit Chinese field labels. Preserve every source character. */
export function evidenceReadingRows(lines: string[]) {
  return lines.map(line => {
    const separator = line.indexOf('：')
    return separator > 0 && separator <= 16
      ? { label: line.slice(0, separator), text: line.slice(separator + 1) }
      : { label: null, text: line }
  })
}
