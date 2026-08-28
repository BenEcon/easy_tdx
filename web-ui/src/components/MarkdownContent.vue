<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, ref } from 'vue'

const props = withDefaults(defineProps<{
  source: string
  ariaLabel?: string
}>(), {
  ariaLabel: 'Markdown 文档',
})

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

const tableBorderPattern = /^[+┌├└┏┣┗╔╠╚][+-─━═┬┼┴┯╋┷┳┻┻╦╬╩┐┤┘┓┫┛╗╣╝]+$/

function isTableBorder(line: string): boolean {
  return tableBorderPattern.test(line.trim())
}

function isTableStart(line: string): boolean {
  const trimmed = line.trim()
  return /^[+┌┏╔]/.test(trimmed) && isTableBorder(trimmed)
}

function isTableEnd(line: string): boolean {
  const trimmed = line.trim()
  return /^[+└┗╚]/.test(trimmed) && isTableBorder(trimmed)
}

function tableCells(line: string): string[] {
  const trimmed = line.trim()
  const delimiter = ['║', '┃', '│', '|'].find(
    (candidate) => trimmed.startsWith(candidate) && trimmed.endsWith(candidate),
  ) ?? ''
  if (!delimiter || !trimmed.endsWith(delimiter)) return []
  return trimmed.slice(1, -1).split(delimiter).map((cell) => cell.trim())
}

function markdownTableCells(line: string): string[] {
  const trimmed = line.trim()
  if (!trimmed.includes('|')) return []
  return trimmed.replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}

function isMarkdownTableSeparator(line: string): boolean {
  const cells = markdownTableCells(line)
  return cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function normalizeMarkdownTables(lines: string[]): string[] {
  const output: string[] = []
  for (let index = 0; index < lines.length; index += 1) {
    const header = lines[index]
    const separator = lines[index + 1] ?? ''
    if (markdownTableCells(header).length >= 2 && isMarkdownTableSeparator(separator)) {
      if (output.length && output.at(-1)?.trim()) output.push('')
      output.push(header.trim(), separator.trim())
      index += 1
      while (index + 1 < lines.length && markdownTableCells(lines[index + 1]).length >= 2) {
        index += 1
        output.push(lines[index].trim())
      }
      output.push('')
      continue
    }
    output.push(header)
  }
  return output
}

function tableGroupRows(lines: string[]): string[][] {
  const rows: string[][] = []
  for (const cells of lines.map(tableCells).filter((item) => item.length)) {
    const previous = rows.at(-1)
    const continuesPrevious = previous && cells.length > 1 && (
      !cells[0] || (/^[)）]$/.test(cells[0]) && cells.slice(1).every((cell) => !cell))
    )
    if (!continuesPrevious) {
      rows.push([...cells])
      continue
    }
    const columnCount = Math.max(previous.length, cells.length)
    for (let column = 0; column < columnCount; column += 1) {
      const fragment = cells[column] ?? ''
      if (fragment) previous[column] = [previous[column], fragment].filter(Boolean).join(' ')
    }
  }
  return rows
}

function renderTdxTable(lines: string[]): string {
  const contentLines = lines.filter((line) => !isTableBorder(line))
  const maxColumns = Math.max(0, ...contentLines.map((line) => tableCells(line).length))
  if (maxColumns < 2) return `\n\`\`\`text\n${lines.join('\n')}\n\`\`\`\n`

  const groups: string[][] = []
  let group: string[] = []
  for (const line of lines.slice(1, -1)) {
    if (isTableBorder(line)) {
      if (group.length) groups.push(group)
      group = []
    } else if (line.trim().startsWith('│')) {
      group.push(line)
    }
  }
  if (group.length) groups.push(group)

  const rows = groups.flatMap(tableGroupRows).filter((cells) => cells.length)
  if (!rows.length) return ''
  const firstLabel = rows[0][0] ?? ''
  const hasHeader = rows[0].length >= 3 || /指标|项目|年份|日期|名称|股东/.test(firstLabel)
  const renderRow = (cells: string[], header = false): string => {
    const tag = header ? 'th' : 'td'
    if (cells.length === 1) {
      return `<tr class="f10-note"><${tag} colspan="${maxColumns}">${escapeHtml(cells[0])}</${tag}></tr>`
    }
    const normalized = [...cells, ...Array(Math.max(0, maxColumns - cells.length)).fill('')]
    return `<tr>${normalized.map((cell) => `<${tag}>${escapeHtml(String(cell))}</${tag}>`).join('')}</tr>`
  }
  const header = hasHeader ? `<thead>${renderRow(rows[0], true)}</thead>` : ''
  const bodyRows = hasHeader ? rows.slice(1) : rows
  return `\n<div class="f10-table-shell"><table class="f10-data-table">${header}<tbody>${bodyRows.map((row) => renderRow(row)).join('')}</tbody></table></div>\n`
}

function fullwidthTableCells(line: string): string[] {
  const trimmed = line.trim()
  if (!trimmed.startsWith('｜') || !trimmed.endsWith('｜')) return []
  return trimmed.slice(1, -1).split('｜').map((cell) => cell.trim())
}

function mergeTableCellFragment(previous: string, fragment: string, forceTight = false): string {
  if (!previous) return fragment
  if (!fragment) return previous
  const tight = forceTight
    || fragment.length <= 2
    || /\|未$/.test(previous)
    || /[\d.]$/.test(previous) && /^\d/.test(fragment)
  return tight ? `${previous}${fragment}` : `${previous} ${fragment}`
}

function cleanRecordLine(value: string): string {
  return value
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^投资者关系活动主要内容\s*/, '')
    .replace(/^介绍\s+(?=\d+[.、])/, '')
    .replace(/^介绍$/, '')
    .replace(/^关于本次活动是否涉\s*/, '')
    .replace(/^及应披露重大信息的\s*/, '')
    .replace(/^说明\s*/, '')
    .replace(/^活动过程中所使用的\s*/, '')
    .replace(/^演示文稿、提供的文档\s*/, '')
    .replace(/^附件（如有，可作为\s*/, '')
    .trim()
}

function recordParagraphs(lines: string[]): string[] {
  const text = lines.join('').replace(/\s+([，。；：！？、])/g, '$1').trim()
  if (!text) return []
  const sentences = text.match(/[^。！？]+[。！？]?/g) ?? [text]
  const paragraphs: string[] = []
  let paragraph = ''
  sentences.forEach((sentence) => {
    if (paragraph && paragraph.length + sentence.length > 330) {
      paragraphs.push(paragraph)
      paragraph = sentence
    } else {
      paragraph += sentence
    }
  })
  if (paragraph) paragraphs.push(paragraph)
  return paragraphs
}

function appendRecordParagraphs(document: Document, parent: HTMLElement, lines: string[]): void {
  recordParagraphs(lines).forEach((value) => {
    const paragraph = document.createElement('p')
    paragraph.textContent = value
    parent.appendChild(paragraph)
  })
}

function appendEditorialContent(document: Document, parent: HTMLElement, lines: string[]): void {
  let paragraphLines: string[] = []
  const flushParagraphs = () => {
    if (!paragraphLines.length) return
    appendRecordParagraphs(document, parent, paragraphLines)
    paragraphLines = []
  }

  lines.map((line) => line.replace(/\s+/g, ' ').trim()).filter(Boolean).forEach((value) => {
    const bracketHeading = value.match(/^【(.+)】$/)
    const numberedHeading = /^(?:[一二三四五六七八九十]+[、.]|\d+[.、])\s*\S+/.test(value)
    const shortHeading = value.length <= 24
      && !/[。！？；：]/.test(value)
      && !/^[-+]?\d+(?:\.\d+)?%?$/.test(value)
    if (bracketHeading || numberedHeading || shortHeading) {
      flushParagraphs()
      const heading = document.createElement('h4')
      heading.textContent = bracketHeading?.[1] ?? value
      parent.appendChild(heading)
      return
    }
    paragraphLines.push(value)
  })
  flushParagraphs()
}

function upgradeFullwidthQuestionAnswer(
  document: Document,
  code: Element,
  rows: string[][],
): boolean {
  const question = rows.find((row) => row.length >= 3 && row.at(-1)?.includes('投资者问'))
  const answer = rows.find((row) => row.length >= 3 && row.at(-1)?.includes('公司答复'))
  if (!question || !answer || !/^\d{4}-\d{2}-\d{2}$/.test(question[0])) return false

  const article = document.createElement('article')
  article.className = 'f10-long-record f10-qa-record'
  const header = document.createElement('header')
  const time = document.createElement('time')
  time.textContent = question[0]
  const title = document.createElement('h3')
  title.textContent = question.slice(1, -1).join(' ')
  header.append(time, title)
  article.appendChild(header)

  const source = document.createElement('span')
  source.className = 'f10-record-source f10-record-source-label'
  source.textContent = '投资者互动'
  article.appendChild(source)

  const body = document.createElement('div')
  body.className = 'f10-record-body'
  const section = document.createElement('section')
  const heading = document.createElement('h4')
  heading.textContent = `公司答复 · ${answer[0]}`
  section.appendChild(heading)
  appendRecordParagraphs(document, section, answer.slice(1, -1))
  body.appendChild(section)
  article.appendChild(body)
  code.closest('pre')?.replaceWith(article)
  return true
}

function upgradeFullwidthEditorial(
  document: Document,
  code: Element,
  rows: string[][],
): boolean {
  const headerRow = rows[0]
  if (
    !headerRow
    || headerRow.length < 3
    || !/^\d{4}-\d{2}-\d{2}$/.test(headerRow[0])
    || !rows.slice(1).some((row) => row.length === 1)
  ) return false

  const article = document.createElement('article')
  article.className = 'f10-long-record f10-editorial-record'
  const header = document.createElement('header')
  const time = document.createElement('time')
  time.textContent = headerRow[0]
  const title = document.createElement('h3')
  title.textContent = headerRow[1]
  header.append(time, title)
  article.appendChild(header)

  if (headerRow[2]) {
    const source = document.createElement('span')
    source.className = 'f10-record-source f10-record-source-label'
    source.textContent = headerRow.slice(2).join(' ')
    article.appendChild(source)
  }

  const body = document.createElement('div')
  body.className = 'f10-record-body f10-editorial-body'
  appendEditorialContent(document, body, rows.slice(1).flat())
  article.appendChild(body)
  code.closest('pre')?.replaceWith(article)
  return true
}

function upgradeFullwidthProfile(
  document: Document,
  code: Element,
  rows: string[][],
): boolean {
  const cells = rows.flat()
  if (!cells.some((cell) => /^姓名[:：]/.test(cell)) || !cells.some((cell) => /^简介[:：]/.test(cell))) {
    return false
  }

  const facts = new Map<string, string>()
  const biography: string[] = []
  let readingBiography = false
  cells.forEach((cell) => {
    const value = cell.replace(/\s+/g, ' ').trim()
    if (!value) return
    if (/^简介[:：]/.test(value)) {
      readingBiography = true
      biography.push(value.replace(/^简介[:：]\s*/, ''))
      return
    }
    if (readingBiography) {
      biography.push(value)
      return
    }
    const pair = value.match(/^([^：:]{1,12})[：:]\s*(.*)$/)
    if (pair) facts.set(pair[1], pair[2] || '—')
  })

  const card = document.createElement('article')
  card.className = 'f10-profile-card'
  const header = document.createElement('header')
  const title = document.createElement('h3')
  title.textContent = facts.get('姓名') ?? '高管资料'
  const role = document.createElement('p')
  role.textContent = facts.get('职务') ?? ''
  header.append(title, role)
  card.appendChild(header)

  const details = document.createElement('dl')
  ;['任职起始日', '性别', '学历', '持股数', '薪酬'].forEach((label) => {
    if (!facts.has(label)) return
    const wrapper = document.createElement('div')
    const term = document.createElement('dt')
    const detail = document.createElement('dd')
    term.textContent = label
    detail.textContent = facts.get(label) ?? '—'
    wrapper.append(term, detail)
    details.appendChild(wrapper)
  })
  if (details.children.length) card.appendChild(details)

  const body = document.createElement('div')
  body.className = 'f10-profile-biography'
  appendRecordParagraphs(document, body, biography)
  card.appendChild(body)
  code.closest('pre')?.replaceWith(card)
  return true
}

function upgradeFullwidthProse(
  document: Document,
  code: Element,
  rows: string[][],
): boolean {
  if (!rows.length || rows.some((row) => row.length !== 1)) return false
  const prose = document.createElement('section')
  prose.className = rows.length === 1 ? 'f10-prose-card f10-prose-summary' : 'f10-prose-card'
  appendEditorialContent(document, prose, rows.flat())
  code.closest('pre')?.replaceWith(prose)
  return true
}

function upgradeFullwidthLongRecord(
  document: Document,
  code: Element,
  rows: string[][],
): boolean {
  const pdfIndex = rows.findIndex((row) => row.length >= 2 && row[0].includes('PDF原文地址'))
  const titleIndex = rows.findIndex((row) => row.length >= 2 && /^\d{4}-\d{2}-\d{2}$/.test(row[0]))
  if (titleIndex < 0 || pdfIndex < 0) return false

  const article = document.createElement('article')
  article.className = 'f10-long-record'

  const header = document.createElement('header')
  const time = document.createElement('time')
  time.textContent = rows[titleIndex][0]
  const title = document.createElement('h3')
  title.textContent = rows[titleIndex].slice(1).join(' ')
  header.append(time, title)
  article.appendChild(header)

  const url = rows[pdfIndex].slice(1).join(' ').trim()
  if (/^https?:\/\/\S+$/i.test(url)) {
    const sourceLink = document.createElement('a')
    sourceLink.className = 'f10-record-source'
    sourceLink.href = url
    sourceLink.target = '_blank'
    sourceLink.rel = 'noopener noreferrer'
    sourceLink.textContent = '查看 PDF 原文'
    article.appendChild(sourceLink)
  }

  const rawLines = rows.slice(pdfIndex + 1).flatMap((row) => row)
  const preamble: string[] = []
  const questions: Array<{ title: string; body: string[] }> = []
  const notes: string[][] = []
  let activeQuestion: { title: string; body: string[] } | undefined
  let activeNote: string[] | undefined

  rawLines.forEach((rawValue) => {
    const raw = rawValue.replace(/\s+/g, ' ').trim()
    const startsNote = /^(关于本次活动是否|活动过程中所使用的)/.test(raw)
    const value = cleanRecordLine(rawValue)

    if (startsNote) {
      activeQuestion = undefined
      activeNote = []
      notes.push(activeNote)
      if (value) activeNote.push(value)
      return
    }
    if (activeNote) {
      if (value) activeNote.push(value)
      return
    }

    const question = value.match(/^(\d+[.、]\s*.+?[？?])\s*(.*)$/)
    if (question) {
      activeQuestion = { title: question[1], body: [] }
      questions.push(activeQuestion)
      if (question[2]) activeQuestion.body.push(question[2])
      return
    }
    if (!value) return
    if (activeQuestion) activeQuestion.body.push(value)
    else preamble.push(value)
  })

  const documentTitle = preamble.find((line) => /活动记录表|调研记录/.test(line))
  if (documentTitle) {
    const label = document.createElement('p')
    label.className = 'f10-record-document-title'
    label.textContent = documentTitle
    article.appendChild(label)
  }

  const facts = document.createElement('dl')
  facts.className = 'f10-record-facts'
  const factPatterns: Array<[string, RegExp]> = [
    ['证券信息', /^(证券代码[:：].+)$/],
    ['参与单位', /^参与单位名称及人员姓名\s*(.+)$/],
    ['时间', /^时间\s*(.+)$/],
    ['地点', /^地点\s*(.+)$/],
    ['形式', /^形式\s*(.+)$/],
  ]
  const usedPreamble = new Set<string>()
  factPatterns.forEach(([label, pattern]) => {
    const line = preamble.find((item) => pattern.test(item))
    const match = line?.match(pattern)
    if (!line || !match) return
    usedPreamble.add(line)
    const wrapper = document.createElement('div')
    const term = document.createElement('dt')
    const detail = document.createElement('dd')
    term.textContent = label
    detail.textContent = match[1]
    wrapper.append(term, detail)
    facts.appendChild(wrapper)
  })
  const categoryLines = preamble.filter((line) => /□|投资者关系活动类别|路演活动|业绩说明会/.test(line))
  if (categoryLines.length) {
    categoryLines.forEach((line) => usedPreamble.add(line))
    const wrapper = document.createElement('div')
    const term = document.createElement('dt')
    const detail = document.createElement('dd')
    term.textContent = '活动类别'
    detail.textContent = categoryLines.join(' ').replace(/^投资者关系活动类别\s*/, '')
    wrapper.append(term, detail)
    facts.appendChild(wrapper)
  }
  if (facts.children.length) article.appendChild(facts)

  const introLines = preamble.filter((line) => (
    line !== documentTitle
    && !usedPreamble.has(line)
    && !/^编号[:：]?$/.test(line)
  ))
  if (introLines.length) {
    const intro = document.createElement('div')
    intro.className = 'f10-record-intro'
    appendRecordParagraphs(document, intro, introLines)
    article.appendChild(intro)
  }

  if (questions.length) {
    const body = document.createElement('div')
    body.className = 'f10-record-body'
    questions.forEach((item) => {
      const section = document.createElement('section')
      const heading = document.createElement('h4')
      heading.textContent = item.title
      section.appendChild(heading)
      appendRecordParagraphs(document, section, item.body)
      body.appendChild(section)
    })
    article.appendChild(body)
  }

  const meaningfulNotes = notes.filter((note) => note.some(Boolean))
  if (meaningfulNotes.length) {
    const footer = document.createElement('footer')
    footer.className = 'f10-record-notes'
    meaningfulNotes.forEach((note) => appendRecordParagraphs(document, footer, note))
    article.appendChild(footer)
  }

  code.closest('pre')?.replaceWith(article)
  return true
}

function upgradeFullwidthCodeTables(document: Document): void {
  document.querySelectorAll('pre > code').forEach((code) => {
    const lines = (code.textContent ?? '').replaceAll('\r\n', '\n').split('\n')
    if (!lines.some((line) => line.trim().startsWith('｜'))) return

    const rows: string[][] = []
    for (const cells of lines.map(fullwidthTableCells).filter((item) => item.length)) {
      const previous = rows.at(-1)
      const continuesMarkedSingle = Boolean(
        previous
        && previous.length === 1
        && cells.length === 1
        && /^(?:★[^:：]+|【[^】]+】)[:：]/.test(previous[0])
        && !/^[★【]/.test(cells[0]),
      )
      const continuesPrevious = continuesMarkedSingle || Boolean(previous && cells.length > 1 && (
        !cells[0] || (/^[)）]$/.test(cells[0]) && cells.slice(1).every((cell) => !cell))
      ))
      if (!continuesPrevious || !previous) {
        rows.push([...cells])
        continue
      }
      const columnCount = Math.max(previous.length, cells.length)
      for (let column = 0; column < columnCount; column += 1) {
        const fragment = cells[column] ?? ''
        if (fragment) previous[column] = mergeTableCellFragment(
          previous[column] ?? '',
          fragment,
          continuesMarkedSingle,
        )
      }
    }

    const columnCount = Math.max(0, ...rows.map((row) => row.length))
    const hasCompleteFrame = lines.some(isTableStart) && lines.some(isTableEnd)
    if (!rows.length || (!hasCompleteFrame && rows.length < 2)) return
    if (upgradeFullwidthLongRecord(document, code, rows)) return
    if (upgradeFullwidthQuestionAnswer(document, code, rows)) return
    if (upgradeFullwidthEditorial(document, code, rows)) return
    if (upgradeFullwidthProfile(document, code, rows)) return
    if (upgradeFullwidthProse(document, code, rows)) return
    if (columnCount < 2) return

    const shell = document.createElement('div')
    shell.className = 'f10-table-shell'
    const table = document.createElement('table')
    table.className = rows.length === 1
      ? 'f10-data-table f10-key-value-table'
      : 'f10-data-table'
    shell.appendChild(table)

    const firstLabel = rows[0][0] ?? ''
    const hasHeader = rows.length > 1 && (
      rows[0].length >= 3 || /指标|项目|年份|日期|名称|股东/.test(firstLabel)
    )
    const body = document.createElement('tbody')
    const appendRow = (parent: HTMLTableSectionElement, cells: string[], header = false) => {
      const row = document.createElement('tr')
      if (cells.length === 1) row.className = 'f10-note'
      const normalized = cells.length === 1
        ? cells
        : [...cells, ...Array(Math.max(0, columnCount - cells.length)).fill('')]
      normalized.forEach((value) => {
        const cell = document.createElement(header ? 'th' : 'td')
        cell.textContent = value
        if (cells.length === 1) cell.colSpan = columnCount
        row.appendChild(cell)
      })
      parent.appendChild(row)
    }

    if (hasHeader) {
      const head = document.createElement('thead')
      appendRow(head, rows[0], true)
      table.appendChild(head)
    }
    rows.slice(hasHeader ? 1 : 0).forEach((row) => appendRow(body, row))
    table.appendChild(body)
    code.closest('pre')?.replaceWith(shell)
  })
}

function enhanceLongRecordNavigation(document: Document): void {
  const records = Array.from(document.querySelectorAll<HTMLElement>('.f10-long-record'))
  if (records.length < 2) return

  const recordLookup = new Map<string, number[]>()
  records.forEach((record, index) => {
    const date = record.querySelector('time')?.textContent?.trim() ?? ''
    const title = record.querySelector('header h3')?.textContent?.trim() ?? ''
    const key = `${date}\u0000${title}`
    const indexes = recordLookup.get(key) ?? []
    indexes.push(index)
    recordLookup.set(key, indexes)
    record.dataset.f10Record = String(index)
    record.hidden = index !== 0
  })

  const candidateTables = Array.from(document.querySelectorAll<HTMLTableElement>('table'))
  let indexTable = candidateTables.find((table) => {
    const rows = Array.from(table.querySelectorAll('tbody tr'))
    if (rows.length < 2 || rows.length > 80) return false
    return rows.every((row) => {
      const cells = row.querySelectorAll('td')
      return cells.length === 2 && /^\d{4}-\d{2}-\d{2}$/.test(cells[0]?.textContent?.trim() ?? '')
    })
  })

  if (!indexTable) {
    const shell = document.createElement('div')
    shell.className = 'f10-table-shell f10-record-index-shell'
    indexTable = document.createElement('table')
    indexTable.className = 'f10-data-table'
    const body = document.createElement('tbody')
    records.forEach((record) => {
      const row = document.createElement('tr')
      const dateCell = document.createElement('td')
      const titleCell = document.createElement('td')
      dateCell.textContent = record.querySelector('time')?.textContent?.trim() ?? ''
      titleCell.textContent = record.querySelector('header h3')?.textContent?.trim() ?? ''
      row.append(dateCell, titleCell)
      body.appendChild(row)
    })
    indexTable.appendChild(body)
    shell.appendChild(indexTable)
    records[0].parentNode?.insertBefore(shell, records[0])
  }

  indexTable.classList.add('f10-record-index-table')
  indexTable.closest('.f10-table-shell')?.classList.add('f10-record-index-shell')
  let linkedCount = 0
  let unavailableCount = 0
  Array.from(indexTable.querySelectorAll('tbody tr')).forEach((row) => {
    const cells = row.querySelectorAll('td')
    const date = cells[0]?.textContent?.trim() ?? ''
    const title = cells[1]?.textContent?.trim() ?? ''
    const indexes = recordLookup.get(`${date}\u0000${title}`)
    const recordIndex = indexes?.shift()
    if (recordIndex === undefined) {
      row.classList.add('is-unavailable')
      const badge = document.createElement('span')
      badge.className = 'f10-record-unavailable'
      badge.textContent = '仅标题'
      badge.title = '数据源未提供正文内容'
      cells[1]?.appendChild(badge)
      unavailableCount += 1
      return
    }
    const trigger = document.createElement('button')
    trigger.type = 'button'
    trigger.className = 'f10-record-trigger'
    trigger.dataset.f10RecordIndex = String(recordIndex)
    trigger.setAttribute('aria-label', `查看 ${date} ${title}`)
    trigger.setAttribute('aria-pressed', recordIndex === 0 ? 'true' : 'false')
    trigger.textContent = title
    cells[1].textContent = ''
    cells[1].appendChild(trigger)
    if (recordIndex === 0) row.classList.add('is-selected')
    linkedCount += 1
  })

  if (!linkedCount) return
  const shell = indexTable.closest('.f10-record-index-shell')
  if (!shell) return
  const navigationHeader = document.createElement('div')
  navigationHeader.className = 'f10-record-index-header'
  const copy = document.createElement('div')
  const heading = document.createElement('strong')
  const pageTitle = document.querySelector('h1')?.textContent ?? ''
  heading.textContent = pageTitle.includes('业内点评') ? '点评目录' : '内容目录'
  const hint = document.createElement('span')
  hint.textContent = unavailableCount
    ? '选择可阅读条目；仅标题表示数据源无正文'
    : '选择条目查看详细内容'
  copy.append(heading, hint)
  const count = document.createElement('small')
  count.textContent = unavailableCount
    ? `${linkedCount} 篇可阅读 · ${unavailableCount} 条仅标题`
    : `${linkedCount} 篇`
  navigationHeader.append(copy, count)
  shell.insertBefore(navigationHeader, indexTable)
}

function alignedCells(line: string): string[] {
  return line.trim().split(/\s{2,}/).map((cell) => cell.trim()).filter(Boolean)
}

function isAlignedTableHeader(line: string): boolean {
  const cells = alignedCells(line)
  return cells.length >= 2 && cells.some((cell) => /编码|名称|日期|项目|指标|年份|类型|备注|金额|比例|股东/.test(cell))
}

function renderAlignedTable(lines: string[]): string {
  const parsed = lines.map(alignedCells).filter((cells) => cells.length >= 2)
  if (parsed.length < 2) return lines.join('\n')
  const columnCount = Math.max(...parsed.map((cells) => cells.length))
  const normalized = parsed.map((cells) => [...cells, ...Array(Math.max(0, columnCount - cells.length)).fill('')])
  const renderRow = (cells: string[], tag: 'th' | 'td') => `<tr>${cells.map((cell) => `<${tag}>${escapeHtml(cell)}</${tag}>`).join('')}</tr>`
  return `\n<div class="f10-table-shell"><table class="f10-data-table"><thead>${renderRow(normalized[0], 'th')}</thead><tbody>${normalized.slice(1).map((row) => renderRow(row, 'td')).join('')}</tbody></table></div>\n`
}

type IndustryTableSchema = {
  headers: string[]
  comparisonHeaders?: string[]
  comparisonValueIndexes?: number[]
}

const industryTableSchemas: Record<string, IndustryTableSchema> = {
  公司行情数据: {
    headers: ['排名', '代码', '简称', '5日涨跌幅(%)', '20日涨跌幅(%)', '60日涨跌幅(%)', '120日涨跌幅(%)', '市盈率(TTM)'],
  },
  公司市值数据: {
    headers: ['排名', '代码', '简称', '股价(元)', '流通A股', '总股数', '流通市值', '总市值'],
  },
  公司主要财务数据: {
    headers: ['排名', '代码', '简称', '每股收益', '每股净资产', '营业收入', '营业利润', '净利润'],
  },
  公司成长能力: {
    headers: ['代码', '简称', '总股本', '实际流通A股', '总资产', '资产排名', '营业收入', '营收排名', '净利润增长率', '增长率排名'],
    comparisonHeaders: ['对比对象', '总股本', '实际流通A股', '总资产', '营业收入', '净利润增长率'],
    comparisonValueIndexes: [0, 1, 2, 3, 5, 7],
  },
  公司收益能力: {
    headers: ['代码', '简称', '销售毛利率(%)', '排名', '销售净利率(%)', '排名', '净资产收益率(%)', '排名', '每股收益', '排名'],
    comparisonHeaders: ['对比对象', '销售毛利率(%)', '销售净利率(%)', '净资产收益率(%)', '每股收益'],
    comparisonValueIndexes: [0, 1, 3, 5, 7],
  },
}

function industryCells(line: string): string[] {
  return line.trim().split(/\s+/).filter(Boolean)
}

function renderIndustryRow(
  cells: string[],
  columnCount: number,
  currentCode: string,
  currentName: string,
): string {
  const normalized = [...cells, ...Array(Math.max(0, columnCount - cells.length)).fill('')].slice(0, columnCount)
  const isCurrent = normalized.includes(currentCode) || normalized[0] === currentName || normalized[1] === currentName
  return `<tr${isCurrent ? ' class="f10-current-row"' : ''}>${normalized.map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`
}

function renderIndustryTable(
  headers: string[],
  rows: string[][],
  currentCode: string,
  currentName: string,
  comparison = false,
): string {
  if (!rows.length) return ''
  const header = `<thead><tr>${headers.map((cell) => `<th>${escapeHtml(cell)}</th>`).join('')}</tr></thead>`
  const body = rows.map((row) => renderIndustryRow(row, headers.length, currentCode, currentName)).join('')
  const tableClass = comparison ? 'f10-industry-table f10-comparison-table' : 'f10-industry-table'
  return `<div class="f10-table-shell f10-industry-shell"><table class="f10-data-table ${tableClass}">${header}<tbody>${body}</tbody></table></div>`
}

function renderIndustryDataset(
  title: string,
  meta: string,
  lines: string[],
  currentCode: string,
  currentName: string,
): string {
  const schema = industryTableSchemas[title]
  if (!schema) return lines.join('\n')

  const meaningful = lines.map((line) => line.trim()).filter(Boolean)
  const headerIndex = meaningful.findIndex((line) => /^(排名|代码)\s+/.test(line))
  if (headerIndex < 0) return lines.join('\n')

  const dataLines = meaningful.slice(headerIndex + 1).filter((line) => !/^─+$/.test(line))
  const comparisonIndex = dataLines.findIndex((line) => line === '与行业指标对比')
  const primaryLines = comparisonIndex >= 0 ? dataLines.slice(0, comparisonIndex) : dataLines
  const comparisonLines = comparisonIndex >= 0 ? dataLines.slice(comparisonIndex + 1) : []
  const primaryRows = primaryLines.map(industryCells).filter((cells) => cells.length >= 2)

  let comparisonRows = comparisonLines.map(industryCells).filter((cells) => cells.length >= 2)
  if (schema.comparisonHeaders && schema.comparisonValueIndexes) {
    comparisonRows = comparisonRows.map((cells) => {
      if (cells.length <= schema.comparisonHeaders!.length) return cells
      return schema.comparisonValueIndexes!.map((index) => cells[index] ?? '')
    })
  }

  const metaHtml = meta
    ? `<p class="f10-dataset-meta">${escapeHtml(meta)}</p>`
    : ''
  const primaryTable = renderIndustryTable(schema.headers, primaryRows, currentCode, currentName)
  const comparisonTable = schema.comparisonHeaders && comparisonRows.length
    ? `<div class="f10-comparison-heading"><span>行业基准</span><strong>与行业指标对比</strong></div>${renderIndustryTable(schema.comparisonHeaders, comparisonRows, currentCode, currentName, true)}`
    : ''

  return `\n<section class="f10-industry-dataset"><header><h3>${escapeHtml(title.replace(/^公司/, ''))}</h3>${metaHtml}</header>${primaryTable}${comparisonTable}</section>\n`
}

function renderTdxRecord(headerLine: string, bodyLines: string[]): string {
  const [date = '', ...titleParts] = headerLine.split('│').map((part) => part.trim())
  const title = titleParts.join(' ').trim()
  const links: string[] = []
  const body = bodyLines.filter((line) => {
    if (/^https?:\/\/\S+$/i.test(line.trim())) {
      links.push(line.trim())
      return false
    }
    return true
  }).map((line) => line.trim()).filter(Boolean).join(' ')
  const bodyRow = body
    ? `<tr class="f10-record-detail"><td colspan="2">${escapeHtml(body)}</td></tr>`
    : ''
  const linkRow = links.length
    ? `<tr class="f10-record-links"><td colspan="2">${links.map((url, index) => `<a href="${escapeHtml(url)}">${links.length > 1 ? `查看附件 ${index + 1}` : '查看原文附件'}</a>`).join('')}</td></tr>`
    : ''
  return `\n<div class="f10-table-shell f10-record-shell"><table class="f10-data-table f10-record-table"><tbody><tr><th>${escapeHtml(date)}</th><td><strong>${escapeHtml(title)}</strong></td></tr>${bodyRow}${linkRow}</tbody></table></div>\n`
}

function isStructuralLine(line: string): boolean {
  const trimmed = line.trim()
  return !trimmed
    || /^[★☆]/.test(trimmed)
    || /^【.+】/.test(trimmed)
    || /^[┌├└┏┣┗╔╠╚｜]/.test(trimmed)
    || /^─{8,}$/.test(trimmed)
    || isAlignedTableHeader(line)
}

function shouldJoinSoftWrappedLine(current: string, next: string): boolean {
  const left = current.trimEnd()
  const right = next.trimStart()
  if (left.length < 54 || isStructuralLine(left) || isStructuralLine(right)) return false
  if (/[。！？；：:）)】]$/.test(left)) return false
  if (/^\d+[、.]/.test(right)) return false
  return true
}

function normalizeTdxContent(source: string): string {
  const lines = source.replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n')
  const output: string[] = []
  const identity = source.match(/◇(\d{6})\s+([^\s更新◇]+)/)
  const currentCode = identity?.[1] ?? ''
  const currentName = identity?.[2] ?? ''
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trimEnd()
    const trimmed = line.trim()
    const industryDataset = trimmed.match(/^【(公司(?:行情数据|市值数据|主要财务数据|成长能力|收益能力))】\s*(.*)$/)
    if (industryDataset) {
      const block: string[] = []
      let cursor = index + 1
      while (cursor < lines.length && !lines[cursor].trim().startsWith('【')) {
        block.push(lines[cursor])
        cursor += 1
      }
      output.push(renderIndustryDataset(
        industryDataset[1],
        industryDataset[2],
        block,
        currentCode,
        currentName,
      ))
      index = cursor - 1
      continue
    }
    if (isTableStart(trimmed)) {
      const table: string[] = [trimmed]
      while (index + 1 < lines.length) {
        index += 1
        const next = lines[index].trim()
        table.push(next)
        if (isTableEnd(next)) break
      }
      output.push(renderTdxTable(table))
      continue
    }
    if (isAlignedTableHeader(line)) {
      const table = [line]
      let cursor = index + 1
      while (cursor < lines.length && lines[cursor].trim() && !lines[cursor].trim().startsWith('【')) {
        const next = lines[cursor]
        if (/^─+$/.test(next.trim())) {
          cursor += 1
          continue
        }
        if (alignedCells(next).length < 2) break
        table.push(next)
        cursor += 1
      }
      if (table.length >= 2) {
        output.push(renderAlignedTable(table))
        index = cursor - 1
        continue
      }
    }
    if (/^─+┬─+$/.test(trimmed)) {
      const headerLine = lines[index + 1]?.trim() ?? ''
      const closingBorder = lines[index + 2]?.trim() ?? ''
      if (headerLine.includes('│') && /^─+┴─+$/.test(closingBorder)) {
        const bodyLines: string[] = []
        let cursor = index + 3
        while (cursor < lines.length) {
          const next = lines[cursor].trim()
          if (!next || /^─+┬─+$/.test(next) || next.startsWith('【') || next.startsWith('┌')) break
          bodyLines.push(lines[cursor])
          cursor += 1
        }
        output.push(renderTdxRecord(headerLine, bodyLines))
        index = cursor - 1
        continue
      }
    }
    const section = trimmed.match(/^【([^【】]+)】$/)
    if (section) {
      output.push(`${/^\d+[.、]/.test(section[1]) ? '##' : '###'} ${section[1]}`)
      continue
    }
    const sectionWithBody = trimmed.match(/^【([^【】]+)】\s+(.+)$/)
    if (sectionWithBody && !sectionWithBody[2].startsWith('【')) {
      output.push(`${/^\d+[.、]/.test(sectionWithBody[1]) ? '##' : '###'} ${sectionWithBody[1]}\n\n${sectionWithBody[2]}`)
      continue
    }
    if (index === 0 && /更新日期|通达信.*F10/.test(trimmed)) {
      output.push(`# ${trimmed}`)
      continue
    }
    if (shouldJoinSoftWrappedLine(line, lines[index + 1] ?? '')) {
      let merged = line.trimEnd()
      let cursor = index + 1
      while (cursor < lines.length && shouldJoinSoftWrappedLine(merged, lines[cursor])) {
        merged += lines[cursor].trimStart()
        cursor += 1
      }
      if (cursor < lines.length && !isStructuralLine(lines[cursor]) && !/[。！？；：:）)】]$/.test(merged)) {
        merged += lines[cursor].trimStart()
        cursor += 1
      }
      output.push(merged)
      index = cursor - 1
      continue
    }
    output.push(line)
  }
  return normalizeMarkdownTables(output).join('\n')
}

const html = computed(() => {
  const parsed = marked.parse(normalizeTdxContent(props.source), {
    async: false,
    breaks: true,
    gfm: true,
  }) as string

  const safe = DOMPurify.sanitize(parsed, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['button', 'form', 'iframe', 'input', 'object', 'style'],
    FORBID_ATTR: ['style'],
  })

  const document = new DOMParser().parseFromString(safe, 'text/html')
  upgradeFullwidthCodeTables(document)
  enhanceLongRecordNavigation(document)
  document.querySelectorAll('table').forEach((table) => {
    if (table.parentElement?.classList.contains('f10-table-shell')) return
    const shell = document.createElement('div')
    shell.className = 'f10-table-shell'
    table.parentNode?.insertBefore(shell, table)
    shell.appendChild(table)
  })
  document.querySelectorAll('a').forEach((link) => {
    link.setAttribute('rel', 'noopener noreferrer')
    if (/^https?:\/\//i.test(link.href)) link.setAttribute('target', '_blank')
  })
  return document.body.innerHTML
})

const readerRef = ref<HTMLElement | null>(null)

function selectLongRecord(index: number, scroll = true): void {
  const reader = readerRef.value
  if (!reader) return
  const records = Array.from(reader.querySelectorAll<HTMLElement>('[data-f10-record]'))
  const selected = records.find((record) => Number(record.dataset.f10Record) === index)
  if (!selected) return

  records.forEach((record) => {
    record.hidden = record !== selected
  })
  reader.querySelectorAll<HTMLElement>('[data-f10-record-index]').forEach((row) => {
    const active = Number(row.dataset.f10RecordIndex) === index
    row.closest('tr')?.classList.toggle('is-selected', active)
    row.setAttribute('aria-pressed', active ? 'true' : 'false')
  })
  if (scroll) {
    window.requestAnimationFrame(() => selected.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
}

function handleContentClick(event: MouseEvent): void {
  const target = event.target instanceof Element
    ? event.target.closest<HTMLElement>('[data-f10-record-index]')
    : null
  if (!target) return
  selectLongRecord(Number(target.dataset.f10RecordIndex))
}

function handleContentKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' && event.key !== ' ') return
  const target = event.target instanceof Element
    ? event.target.closest<HTMLElement>('[data-f10-record-index]')
    : null
  if (!target) return
  event.preventDefault()
  selectLongRecord(Number(target.dataset.f10RecordIndex))
}
</script>

<template>
  <div
    ref="readerRef"
    class="markdown-reader"
    :aria-label="ariaLabel"
    @click="handleContentClick"
    @keydown="handleContentKeydown"
    v-html="html"
  />
</template>

<style scoped>
.markdown-reader {
  min-height: 0;
  height: 100%;
  padding: 22px clamp(18px, 3.2vw, 42px) 34px;
  overflow: auto;
  color: #c9cad1;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.024), transparent 70px),
    rgba(8, 9, 12, 0.34);
  border: 1px solid var(--border);
  border-radius: 10px;
  font-size: 12px;
  line-height: 1.82;
  overflow-wrap: anywhere;
  animation: markdown-enter 180ms ease-out both;
}

.markdown-reader :deep(> :first-child) { margin-top: 0; }
.markdown-reader :deep(> :last-child) { margin-bottom: 0; }
.markdown-reader :deep(p) {
  margin: 0 0 12px;
  text-align: justify;
  text-align-last: left;
  text-justify: inter-character;
}
.markdown-reader :deep(h1),
.markdown-reader :deep(h2),
.markdown-reader :deep(h3),
.markdown-reader :deep(h4),
.markdown-reader :deep(h5),
.markdown-reader :deep(h6) {
  margin: 24px 0 10px;
  color: var(--text);
  font-weight: 650;
  line-height: 1.38;
  letter-spacing: -0.012em;
}
.markdown-reader :deep(h1) { font-size: 20px; }
.markdown-reader :deep(h2) {
  padding-bottom: 7px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.09);
  font-size: 16px;
}
.markdown-reader :deep(h3) { font-size: 14px; }
.markdown-reader :deep(h4),
.markdown-reader :deep(h5),
.markdown-reader :deep(h6) { font-size: 12px; }
.markdown-reader :deep(strong) { color: #ececf0; font-weight: 650; }
.markdown-reader :deep(em) { color: #d8d8de; }
.markdown-reader :deep(a) {
  color: #66b5ff;
  text-decoration-color: rgba(102, 181, 255, 0.36);
  text-underline-offset: 3px;
  transition: color 140ms ease, text-decoration-color 140ms ease;
}
.markdown-reader :deep(a:hover) {
  color: #9bcfff;
  text-decoration-color: currentColor;
}
.markdown-reader :deep(ul),
.markdown-reader :deep(ol) { margin: 8px 0 14px; padding-left: 22px; }
.markdown-reader :deep(li) { margin: 3px 0; padding-left: 2px; }
.markdown-reader :deep(li::marker) { color: #65aef5; }
.markdown-reader :deep(blockquote) {
  margin: 15px 0;
  padding: 9px 14px;
  color: var(--text-muted);
  background: rgba(10, 132, 255, 0.055);
  border-left: 2px solid rgba(82, 168, 255, 0.55);
  border-radius: 0 7px 7px 0;
}
.markdown-reader :deep(blockquote p:last-child) { margin-bottom: 0; }
.markdown-reader :deep(hr) {
  height: 1px;
  margin: 22px 0;
  background: rgba(255, 255, 255, 0.09);
  border: 0;
}
.markdown-reader :deep(code) {
  padding: 2px 5px;
  color: #d7eaff;
  background: rgba(10, 132, 255, 0.09);
  border: 1px solid rgba(10, 132, 255, 0.13);
  border-radius: 5px;
  font: 0.92em/1.55 var(--font-mono);
}
.markdown-reader :deep(pre) {
  margin: 14px 0;
  padding: 14px 16px;
  overflow: auto;
  color: #cfd0d7;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border);
  border-radius: 9px;
}
.markdown-reader :deep(pre code) {
  padding: 0;
  color: inherit;
  background: transparent;
  border: 0;
  font-size: 10.5px;
  white-space: pre;
}
.markdown-reader :deep(.f10-table-shell) {
  max-width: 100%;
  margin: 15px 0 18px;
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 9px;
}
.markdown-reader :deep(table) {
  width: 100%;
  margin: 15px 0 18px;
  overflow: hidden;
  border-collapse: separate;
  border-spacing: 0;
  border: 1px solid var(--border);
  border-radius: 9px;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.markdown-reader :deep(.f10-table-shell table) {
  margin: 0;
  border: 0;
  border-radius: 0;
}
.markdown-reader :deep(.f10-key-value-table td:first-child) {
  width: 170px;
  min-width: 170px;
  color: #a9d3ff;
  background: rgba(10, 132, 255, 0.055);
  font-weight: 620;
  white-space: nowrap;
}
.markdown-reader :deep(.f10-key-value-table td:last-child) {
  color: #e2e3e9;
  font-weight: 520;
}
.markdown-reader :deep(.f10-industry-dataset) {
  margin: 20px 0 26px;
}
.markdown-reader :deep(.f10-industry-dataset > header) {
  display: flex;
  min-height: 30px;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 8px;
  padding: 0 2px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.075);
}
.markdown-reader :deep(.f10-industry-dataset > header h3) {
  margin: 0;
  padding-bottom: 8px;
  color: #eef5ff;
  font-size: 13px;
  letter-spacing: 0;
}
.markdown-reader :deep(.f10-dataset-meta) {
  margin: 0 0 0 auto;
  color: var(--text-dim);
  font-size: 9px;
  white-space: nowrap;
}
.markdown-reader :deep(.f10-industry-shell) {
  margin: 0;
  background: rgba(0, 0, 0, 0.1);
  border-color: rgba(255, 255, 255, 0.075);
}
.markdown-reader :deep(.f10-industry-table) {
  min-width: 760px;
}
.markdown-reader :deep(.f10-industry-table th) {
  position: sticky;
  z-index: 1;
  top: 0;
  padding-block: 9px;
  color: #aeb1ba;
  background: #1c1e24;
  font-size: 9px;
  font-weight: 620;
  letter-spacing: 0.015em;
}
.markdown-reader :deep(.f10-industry-table td) {
  padding-block: 9px;
  color: #cfd1d8;
  white-space: nowrap;
}
.markdown-reader :deep(.f10-industry-table th:first-child),
.markdown-reader :deep(.f10-industry-table td:first-child) {
  min-width: 58px;
  padding-left: 13px;
}
.markdown-reader :deep(.f10-industry-table th:nth-child(2)),
.markdown-reader :deep(.f10-industry-table td:nth-child(2)) {
  min-width: 76px;
}
.markdown-reader :deep(.f10-industry-table tbody tr:nth-child(even):not(.f10-current-row)) {
  background: rgba(255, 255, 255, 0.012);
}
.markdown-reader :deep(.f10-industry-table .f10-current-row) {
  background: linear-gradient(90deg, rgba(10, 132, 255, 0.145), rgba(10, 132, 255, 0.035));
  box-shadow: inset 2px 0 #3b9eff;
}
.markdown-reader :deep(.f10-industry-table .f10-current-row td) {
  color: #e7f3ff;
  font-weight: 610;
}
.markdown-reader :deep(.f10-comparison-heading) {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 14px 2px 8px;
}
.markdown-reader :deep(.f10-comparison-heading span) {
  padding: 2px 6px;
  color: #82c2ff;
  background: rgba(10, 132, 255, 0.09);
  border: 1px solid rgba(10, 132, 255, 0.16);
  border-radius: 5px;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.06em;
}
.markdown-reader :deep(.f10-comparison-heading strong) {
  color: #d8dae1;
  font-size: 11px;
  font-weight: 620;
}
.markdown-reader :deep(.f10-comparison-table) {
  min-width: 620px;
}
.markdown-reader :deep(.f10-comparison-table th:first-child),
.markdown-reader :deep(.f10-comparison-table td:first-child) {
  min-width: 118px;
}
.markdown-reader :deep(th),
.markdown-reader :deep(td) {
  min-width: 84px;
  padding: 8px 10px;
  border-right: 1px solid rgba(255, 255, 255, 0.055);
  border-bottom: 1px solid rgba(255, 255, 255, 0.055);
  text-align: left;
  vertical-align: top;
}
.markdown-reader :deep(th) {
  color: #e5e5ea;
  background: rgba(255, 255, 255, 0.052);
  font-weight: 620;
  white-space: nowrap;
}
.markdown-reader :deep(tr:last-child td) { border-bottom: 0; }
.markdown-reader :deep(th:last-child),
.markdown-reader :deep(td:last-child) { border-right: 0; }
.markdown-reader :deep(tbody tr) { transition: background-color 130ms ease; }
.markdown-reader :deep(tbody tr:hover) { background: rgba(10, 132, 255, 0.045); }
.markdown-reader :deep(.f10-note td) {
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.018);
}
.markdown-reader :deep(.f10-record-shell) { margin: 10px 0; }
.markdown-reader :deep(.f10-record-table th) {
  width: 122px;
  min-width: 122px;
  color: #9fcfff;
  background: rgba(10, 132, 255, 0.065);
  font-weight: 600;
  text-align: center;
}
.markdown-reader :deep(.f10-record-table td) { min-width: 0; }
.markdown-reader :deep(.f10-record-table strong) { font-weight: 620; }
.markdown-reader :deep(.f10-record-detail td) {
  padding: 11px 13px;
  color: var(--text-muted);
  line-height: 1.78;
}
.markdown-reader :deep(.f10-record-links td) {
  padding-top: 7px;
  padding-bottom: 8px;
  background: rgba(255, 255, 255, 0.015);
}
.markdown-reader :deep(.f10-record-links a) {
  display: inline-flex;
  margin-right: 14px;
  font-size: 10.5px;
  font-weight: 570;
}
.markdown-reader :deep(.f10-record-index-shell) {
  margin-bottom: 24px;
  overflow: hidden;
}
.markdown-reader :deep(.f10-record-index-header) {
  display: flex;
  min-height: 48px;
  align-items: center;
  padding: 9px 12px;
  background: rgba(255, 255, 255, 0.022);
  border-bottom: 1px solid rgba(255, 255, 255, 0.065);
}
.markdown-reader :deep(.f10-record-index-header > div) {
  display: flex;
  flex-direction: column;
}
.markdown-reader :deep(.f10-record-index-header strong) {
  color: #e4e7ed;
  font-size: 11px;
  font-weight: 640;
}
.markdown-reader :deep(.f10-record-index-header span) {
  margin-top: 1px;
  color: var(--text-dim);
  font-size: 8.5px;
}
.markdown-reader :deep(.f10-record-index-header small) {
  margin-left: auto;
  padding: 2px 6px;
  color: #8bc7ff;
  background: rgba(10, 132, 255, 0.075);
  border-radius: 5px;
  font-size: 8px;
  font-weight: 680;
}
.markdown-reader :deep(.f10-record-index-table) {
  table-layout: fixed;
}
.markdown-reader :deep(.f10-record-index-table td:first-child) {
  width: 112px;
  min-width: 112px;
  color: #91949e;
  font: 9.5px var(--font-mono);
}
.markdown-reader :deep(.f10-record-index-table td:last-child) {
  position: relative;
  padding: 0;
  color: #c9cbd2;
  white-space: normal;
  overflow-wrap: anywhere;
}
.markdown-reader :deep(.f10-record-trigger) {
  position: relative;
  display: block;
  width: 100%;
  min-height: 38px;
  padding: 8px 32px 8px 10px;
  color: inherit;
  background: transparent;
  border: 0;
  border-radius: 0;
  box-shadow: none;
  font: inherit;
  line-height: 1.55;
  text-align: left;
  white-space: normal;
  overflow-wrap: anywhere;
  cursor: pointer;
}
.markdown-reader :deep(.f10-record-index-table tr.is-unavailable td:last-child) {
  padding: 8px 68px 8px 10px;
  color: #777a84;
}
.markdown-reader :deep(.f10-record-unavailable) {
  position: absolute;
  top: 50%;
  right: 10px;
  padding: 2px 6px;
  color: #777b85;
  background: rgba(255, 255, 255, 0.028);
  border: 1px solid rgba(255, 255, 255, 0.055);
  border-radius: 5px;
  font-size: 8px;
  font-weight: 620;
  white-space: nowrap;
  transform: translateY(-50%);
}
.markdown-reader :deep(.f10-record-trigger::after) {
  position: absolute;
  top: 50%;
  right: 12px;
  color: #5f626b;
  content: '›';
  font-size: 16px;
  transform: translateY(-52%);
  transition: color 130ms ease, transform 130ms ease;
}
.markdown-reader :deep(.f10-record-index-table tr:has(.f10-record-trigger:hover)),
.markdown-reader :deep(.f10-record-index-table tr:has(.f10-record-trigger:focus-visible)) {
  background: rgba(10, 132, 255, 0.055);
}
.markdown-reader :deep(.f10-record-trigger:focus-visible) {
  outline: 1px solid rgba(91, 174, 255, 0.5);
  outline-offset: -2px;
}
.markdown-reader :deep(.f10-record-trigger:hover::after),
.markdown-reader :deep(.f10-record-trigger:focus-visible::after) {
  color: #8cc8ff;
  transform: translate(2px, -52%);
}
.markdown-reader :deep(.f10-record-index-table tr.is-selected) {
  background: linear-gradient(90deg, rgba(10, 132, 255, 0.13), rgba(10, 132, 255, 0.035));
  box-shadow: inset 2px 0 #3b9eff;
}
.markdown-reader :deep(.f10-record-index-table tr.is-selected td) {
  color: #e4f1ff;
  font-weight: 610;
}
.markdown-reader :deep(.f10-record-index-table tr.is-selected .f10-record-trigger::after) {
  color: #8cc8ff;
}
.markdown-reader :deep(.f10-long-record) {
  position: relative;
  min-width: 0;
  margin: 22px 0 34px;
  padding: 0 2px 28px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.09);
  overflow: visible;
}
.markdown-reader :deep(.f10-long-record[hidden]) { display: none; }
.markdown-reader :deep(.f10-long-record > header) {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr);
  align-items: baseline;
  gap: 14px;
  margin-bottom: 10px;
  padding-bottom: 11px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.075);
}
.markdown-reader :deep(.f10-long-record > header time) {
  color: #86c4ff;
  font: 9.5px var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.markdown-reader :deep(.f10-long-record > header h3) {
  margin: 0;
  color: #eef1f7;
  font-size: 14px;
  font-weight: 650;
  letter-spacing: -0.008em;
  white-space: normal;
  overflow-wrap: anywhere;
}
.markdown-reader :deep(.f10-record-source) {
  display: inline-flex;
  min-height: 25px;
  align-items: center;
  margin: 0 0 14px 104px;
  padding: 0 9px;
  color: #8bc7ff;
  background: rgba(10, 132, 255, 0.065);
  border: 1px solid rgba(10, 132, 255, 0.15);
  border-radius: 6px;
  font-size: 9px;
  font-weight: 620;
  text-decoration: none;
}
.markdown-reader :deep(.f10-record-source:hover) {
  color: #c6e4ff;
  background: rgba(10, 132, 255, 0.11);
}
.markdown-reader :deep(.f10-record-source-label) {
  color: #9ba8b8;
  background: rgba(255, 255, 255, 0.028);
  border-color: rgba(255, 255, 255, 0.065);
  cursor: default;
}
.markdown-reader :deep(.f10-record-document-title) {
  margin: 2px 0 11px 104px;
  color: #dfe2e9;
  font-size: 12px;
  font-weight: 630;
}
.markdown-reader :deep(.f10-record-facts) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 22px;
  margin: 0 0 18px 104px;
  padding: 10px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.055);
  border-bottom: 1px solid rgba(255, 255, 255, 0.055);
}
.markdown-reader :deep(.f10-record-facts > div) {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 8px;
  padding: 5px 0;
}
.markdown-reader :deep(.f10-record-facts dt) {
  color: var(--text-dim);
  font-size: 9px;
}
.markdown-reader :deep(.f10-record-facts dd) {
  margin: 0;
  color: #c7c9d0;
  font-size: 10px;
  line-height: 1.6;
}
.markdown-reader :deep(.f10-record-intro),
.markdown-reader :deep(.f10-record-body),
.markdown-reader :deep(.f10-record-notes) {
  max-width: 920px;
  margin-left: 104px;
}
.markdown-reader :deep(.f10-record-intro) {
  margin-bottom: 16px;
  color: var(--text-muted);
}
.markdown-reader :deep(.f10-record-body > section) {
  margin: 0;
  padding: 18px 0 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.065);
}
.markdown-reader :deep(.f10-record-body h4) {
  margin: 0 0 9px;
  color: #e8ebf2;
  font-size: 12.5px;
  font-weight: 650;
}
.markdown-reader :deep(.f10-record-body p),
.markdown-reader :deep(.f10-record-intro p) {
  margin: 0 0 9px;
  color: #c5c7ce;
  font-size: 11.5px;
  line-height: 1.92;
  text-align: justify;
  text-align-last: left;
  text-justify: inter-character;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.markdown-reader :deep(.f10-record-body p:last-child),
.markdown-reader :deep(.f10-record-intro p:last-child) {
  margin-bottom: 0;
}
.markdown-reader :deep(.f10-record-notes) {
  margin-top: 18px;
  padding: 12px 14px;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.018);
  border-left: 2px solid rgba(10, 132, 255, 0.32);
  border-radius: 0 7px 7px 0;
}
.markdown-reader :deep(.f10-record-notes p) {
  margin: 0 0 7px;
  font-size: 10px;
  line-height: 1.75;
}
.markdown-reader :deep(.f10-record-notes p:last-child) { margin-bottom: 0; }
.markdown-reader :deep(.f10-editorial-body > h4) {
  margin: 20px 0 8px;
  padding-top: 16px;
  color: #e8ebf2;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 12.5px;
}
.markdown-reader :deep(.f10-editorial-body > h4:first-child) {
  margin-top: 0;
  padding-top: 0;
  border-top: 0;
}
.markdown-reader :deep(.f10-editorial-body > p) {
  margin: 0 0 11px;
  color: #c5c7ce;
  font-size: 11.5px;
  line-height: 1.92;
  text-align: justify;
  text-align-last: left;
  text-justify: inter-character;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.markdown-reader :deep(.f10-qa-record .f10-record-body > section) {
  padding-top: 14px;
}
.markdown-reader :deep(.f10-prose-card) {
  max-width: 980px;
  margin: 14px 0 20px;
  padding: 18px 20px;
  color: #c7c9d0;
  background: linear-gradient(135deg, rgba(10, 132, 255, 0.045), rgba(255, 255, 255, 0.012));
  border: 1px solid rgba(255, 255, 255, 0.075);
  border-radius: 9px;
}
.markdown-reader :deep(.f10-prose-card h4) {
  margin: 20px 0 8px;
  color: #e6e9ef;
  font-size: 12.5px;
}
.markdown-reader :deep(.f10-prose-card h4:first-child) { margin-top: 0; }
.markdown-reader :deep(.f10-prose-card p) {
  margin: 0 0 11px;
  font-size: 11.5px;
  line-height: 1.92;
  text-align: justify;
  text-align-last: left;
  text-justify: inter-character;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.markdown-reader :deep(.f10-prose-card p:last-child) { margin-bottom: 0; }
.markdown-reader :deep(.f10-prose-summary) {
  padding: 15px 17px;
  border-left: 2px solid rgba(79, 164, 247, 0.55);
}
.markdown-reader :deep(.f10-profile-card) {
  max-width: 980px;
  margin: 14px 0;
  padding: 17px 19px 19px;
  background: rgba(255, 255, 255, 0.015);
  border: 1px solid rgba(255, 255, 255, 0.075);
  border-radius: 9px;
}
.markdown-reader :deep(.f10-profile-card > header) {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 11px;
}
.markdown-reader :deep(.f10-profile-card > header h3) {
  margin: 0;
  color: #eef1f7;
  font-size: 14px;
}
.markdown-reader :deep(.f10-profile-card > header p) {
  margin: 0;
  color: #8fc8ff;
  font-size: 10px;
}
.markdown-reader :deep(.f10-profile-card dl) {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  margin: 0 0 14px;
}
.markdown-reader :deep(.f10-profile-card dl > div) {
  min-width: 0;
  padding: 8px 9px;
  background: rgba(255, 255, 255, 0.018);
  border-radius: 6px;
}
.markdown-reader :deep(.f10-profile-card dt) {
  margin-bottom: 2px;
  color: var(--text-dim);
  font-size: 8px;
}
.markdown-reader :deep(.f10-profile-card dd) {
  margin: 0;
  color: #d6d8df;
  font-size: 10px;
  overflow-wrap: anywhere;
}
.markdown-reader :deep(.f10-profile-biography) {
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.markdown-reader :deep(.f10-profile-biography p) {
  margin: 0 0 10px;
  color: #bfc2ca;
  font-size: 11px;
  line-height: 1.9;
  text-align: justify;
  text-align-last: left;
  text-justify: inter-character;
  white-space: normal;
  overflow-wrap: anywhere;
}
.markdown-reader :deep(.f10-profile-biography p:last-child) { margin-bottom: 0; }
.markdown-reader :deep(img) {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 16px auto;
  border: 1px solid var(--border);
  border-radius: 9px;
}

@keyframes markdown-enter {
  from { opacity: 0; transform: translateY(3px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .markdown-reader { animation: none; }
}

@media (max-width: 760px) {
  .markdown-reader :deep(.f10-industry-dataset > header) {
    align-items: flex-start;
    flex-direction: column;
    gap: 0;
  }
  .markdown-reader :deep(.f10-dataset-meta) {
    margin: -5px 0 8px;
    white-space: normal;
  }
  .markdown-reader :deep(.f10-long-record > header) {
    grid-template-columns: 1fr;
    gap: 4px;
  }
  .markdown-reader :deep(.f10-record-source),
  .markdown-reader :deep(.f10-record-document-title),
  .markdown-reader :deep(.f10-record-facts),
  .markdown-reader :deep(.f10-record-intro),
  .markdown-reader :deep(.f10-record-body),
  .markdown-reader :deep(.f10-record-notes) {
    margin-left: 0;
  }
  .markdown-reader :deep(.f10-record-facts) { grid-template-columns: 1fr; }
  .markdown-reader :deep(.f10-profile-card dl) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
