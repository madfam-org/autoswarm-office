module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // The conventional types, plus the two this repo's automation actually
    // writes. `deploy` is emitted by .github/workflows/promote-to-prod.yml and
    // the staging digest job; `rollback` by .github/workflows/rollback-prod.yml.
    // Leaving them out would mean the hook rejects our own release tooling.
    'type-enum': [
      2,
      'always',
      [
        'build',
        'chore',
        'ci',
        'deploy',
        'docs',
        'feat',
        'fix',
        'perf',
        'refactor',
        'revert',
        'rollback',
        'style',
        'test',
      ],
    ],
    // Keep SHOUTING and PascalCase subjects out, but allow the milestone
    // prefixes this team actually uses ("feat(office-ui): E1 - ...",
    // "feat(billing): M3 - ..."). The stock list also bans sentence-case and
    // start-case, which rejected 11 of the last 200 commits for a deliberate
    // convention. Genuinely typeless messages are still caught by type-enum.
    'subject-case': [2, 'never', ['pascal-case', 'upper-case']],
    // Off: the bodies of `deploy(prod)`/`rollback(prod)` commits are generated
    // by .github/workflows/{promote-to-prod,rollback-prod}.yml from an
    // operator-supplied free-text reason, so a long sentence at the console
    // would trip this. It also fires on pasted URLs and stack traces. A rule
    // the release path can break by accident is a rule that gets deleted.
    'body-max-line-length': [0],
    // No scope-enum on purpose. The previous allow-list named 16 scopes; the
    // last 200 commits used 33, and it was the single largest source of
    // violations (156 of them). No document has ever described a scope
    // allow-list -- AGENTS.md specifies types only -- so an enum here enforces
    // a policy nobody wrote down and would reject each new app or subsystem on
    // its first commit. Scopes stay free-form and descriptive.
  },
};
