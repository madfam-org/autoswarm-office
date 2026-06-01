if (process.env.LOCAL_DESTRUCTIVE !== 'yes') {
  console.error('Refusing destructive local cleanup without LOCAL_DESTRUCTIVE=yes.');
  process.exit(1);
}
