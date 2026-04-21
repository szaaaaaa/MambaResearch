/** 解析 SSE 文本块为 {event, data} 数组，event 缺省 'message'，空 data 丢弃 */
export function parseSseFrames(chunk: string): Array<{ event: string; data: string }> {
  return chunk
    .split('\n\n')
    .map((frame) => frame.trim())
    .filter(Boolean)
    .map((frame) => {
      let event = 'message';
      const dataLines: string[] = [];
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) {
          event = line.slice(6).trim();
          continue;
        }
        if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trim());
        }
      }
      return { event, data: dataLines.join('\n') };
    })
    .filter((frame) => frame.data);
}
