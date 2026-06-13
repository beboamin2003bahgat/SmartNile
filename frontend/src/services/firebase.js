// src/services/firebase.js
// ========================
// Single Firebase app instance for the entire dashboard.
// Import { db, storage } from here — never call initializeApp() again.
//
// Setup:
//   1. npm install firebase
//   2. Copy your firebaseConfig from Firebase Console →
//      Project Settings → Your apps → Web app → SDK snippet
//   3. Paste the values into .env.local:
//        REACT_APP_FIREBASE_API_KEY=...
//        REACT_APP_FIREBASE_AUTH_DOMAIN=...
//        REACT_APP_FIREBASE_PROJECT_ID=...
//        REACT_APP_FIREBASE_STORAGE_BUCKET=...
//        REACT_APP_FIREBASE_MESSAGING_SENDER_ID=...
//        REACT_APP_FIREBASE_APP_ID=...

import { initializeApp } from "firebase/app";
import {
  getFirestore,
  collection,
  query,
  orderBy,
  limit,
  onSnapshot,
  getDocs,
  where,
  Timestamp,
  doc,
} from "firebase/firestore";
import { getStorage } from "firebase/storage";

// ── Config from environment variables ────────────────────────────────────────
const firebaseConfig = {
  apiKey:            process.env.REACT_APP_FIREBASE_API_KEY,
  authDomain:        process.env.REACT_APP_FIREBASE_AUTH_DOMAIN,
  projectId:         process.env.REACT_APP_FIREBASE_PROJECT_ID,
  storageBucket:     process.env.REACT_APP_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.REACT_APP_FIREBASE_MESSAGING_SENDER_ID,
  appId:             process.env.REACT_APP_FIREBASE_APP_ID,
};

// ── Initialise once ───────────────────────────────────────────────────────────
const app     = initializeApp(firebaseConfig);
export const db      = getFirestore(app);
export const storage = getStorage(app);

// ── Re-export Firestore helpers so hooks don't import firebase directly ───────
export {
  collection,
  query,
  orderBy,
  limit,
  onSnapshot,
  getDocs,
  where,
  Timestamp,
  doc,
};

export default app;
