import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: false,
})

export const renderMarkdown = (text: string) => md.render(text || '')
