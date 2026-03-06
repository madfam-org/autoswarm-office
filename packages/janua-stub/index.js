'use client';
const React = require('react');

function JanuaProvider({ children }) {
  return children;
}

function useJanua() {
  return {
    user: null,
    isAuthenticated: false,
    isLoading: false,
    signIn: () => {},
    signOut: () => {},
  };
}

function SignIn({ redirectUrl }) {
  return null;
}

module.exports = { JanuaProvider, useJanua, SignIn };
