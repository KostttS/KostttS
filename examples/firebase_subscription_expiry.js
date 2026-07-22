const { onSchedule } = require("firebase-functions/v2/scheduler");
const { initializeApp } = require("firebase-admin/app");
const {
  FieldValue,
  Timestamp,
  getFirestore,
} = require("firebase-admin/firestore");

initializeApp();

const db = getFirestore();

/// Sanitized scheduled-function example.
///
/// Checks active subscriptions in bounded batches and changes expired records
/// to an inactive state. Adapt collection names and downstream product rules
/// to the application.
exports.expireSubscriptions = onSchedule(
  {
    schedule: "every 60 minutes",
    region: "europe-west1",
    timeZone: "UTC",
  },
  async () => {
    const now = Timestamp.now();

    const snapshot = await db
      .collection("subscriptions")
      .where("status", "==", "active")
      .where("expiresAt", "<=", now)
      .limit(400)
      .get();

    if (snapshot.empty) {
      return;
    }

    const batch = db.batch();

    for (const document of snapshot.docs) {
      batch.update(document.ref, {
        status: "expired",
        active: false,
        updatedAt: FieldValue.serverTimestamp(),
      });
    }

    await batch.commit();
  },
);
