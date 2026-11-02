export class Signal<T = void> {
  private listeners = new Set<(arg: T) => void>();
  add(fn: (arg: T) => void): void {
    this.listeners.add(fn);
  }
  remove(fn: (arg: T) => void): void {
    this.listeners.delete(fn);
  }
  dispatch(arg: T): void {
    for (const fn of this.listeners) fn(arg);
  }
  clear(): void {
    this.listeners.clear();
  }
}
