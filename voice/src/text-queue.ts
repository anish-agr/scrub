// Ordered within a Photon thread, independent across threads. Completed tails never accumulate.
export class TextQueues {
  private tails = new Map<string, Promise<void>>();
  get size() { return this.tails.size; }
  enqueue(thread: string, work: () => Promise<void>): Promise<void> {
    const task = (this.tails.get(thread) || Promise.resolve()).then(work);
    const tail = task.finally(() => {
      if (this.tails.get(thread) === tail) this.tails.delete(thread);
    });
    this.tails.set(thread, tail);
    return tail;
  }
  async drain() { await Promise.all(this.tails.values()); }
}
