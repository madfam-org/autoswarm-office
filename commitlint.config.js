module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'scope-enum': [
      2,
      'always',
      [
        'nexus-api',
        'office-ui',
        'admin',
        'gateway',
        'colyseus',
        'workers',
        'config',
        'shared-types',
        'ui',
        'inference',
        'orchestrator',
        'permissions',
        'infra',
        'docs',
        'ci',
        'deps',
      ],
    ],
  },
};
