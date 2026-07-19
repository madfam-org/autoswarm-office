import { describe, it, expect } from 'vitest';
import { WFCGrid, buildOfficeRules } from '../index';

/**
 * Guards the OfficeSizePicker onboarding preview (office-ui), the first real
 * consumer of this package. Each size bucket seeds the WFC with a department
 * count; these assert generation converges and emits only tile types the
 * picker's tileColor() can render.
 */
describe('OfficeSizePicker preview generation', () => {
  for (const depts of [3, 4, 6, 8, 10]) {
    it(`generates a varied ${depts}-department office grid`, () => {
      const { rules, allTiles } = buildOfficeRules(depts);
      const grid = new WFCGrid({
        width: 32,
        height: 22,
        rules,
        allTiles,
        seed: depts * 1000 + 7,
        maxRetries: 6,
      });
      const result = grid.run();
      expect(result).not.toBeNull();
      expect(result!.length).toBe(22);
      expect(result![0].length).toBe(32);
      const deptCells = result!
        .flat()
        .filter((t) => t.startsWith('dept_') && !t.startsWith('dept_wall')).length;
      expect(deptCells).toBeGreaterThan(0);
    });
  }

  it('emits only tile types the picker knows how to color', () => {
    const { rules, allTiles } = buildOfficeRules(6);
    const grid = new WFCGrid({ width: 32, height: 22, rules, allTiles, seed: 6007, maxRetries: 6 });
    const result = grid.run()!;
    const known = (t: string) =>
      t === 'wall' ||
      t === 'corridor' ||
      t === 'floor' ||
      t.startsWith('dept_wall_') ||
      t.startsWith('dept_');
    const unknown = [...new Set(result.flat())].filter((t) => !known(t));
    expect(unknown).toEqual([]);
  });
});
