// --- AUTHENTICATION ---

/**
 * Initializes the Google Identity Services client. This is called once on page load.
 */
function initializeIdentityServices() {
  if (!OAUTH_CLIENT_ID || !GCP_PROJECT_ID) {
    updateStatus('Configuration missing. Please set up config.js.', 'error');
    return;
  }
  if (typeof google === 'undefined' || !google.accounts) {
    updateStatus('Google Identity Services failed to load.', 'error');
    console.error('GSI client library not loaded or initialized.');
    return;
  }
  try {
    // Initialize the token client for handling OAuth 2.0 flow.
    tokenClient = google.accounts.oauth2.initTokenClient({
      client_id: OAUTH_CLIENT_ID,
      scope: BQ_SCOPES,
      callback: () => {}, // Callback is handled by the promise in ensureAccessToken.
    });
  } catch (error) {
    updateStatus('Could not initialize Google Identity Services.', 'error');
    console.error(error);
  }
}

/**
 * Handles clicks on the main authorization button (sign-in or sign-out).
 */
function handleAuthClick() {
  if (userSignedIn) {
    // If the user is signed in, revoke the token and sign out.
    if (accessToken) {
      google.accounts.oauth2.revoke(accessToken, () => {});
    }
    accessToken = null;
    resetSignedInUi();
  } else {
    // If the user is signed out, start the sign-in process.
    ensureAccessToken({ prompt: 'consent' });
  }
}

/**
 * Gets a valid access token, prompting the user for consent if necessary.
 * @param {object} options - Options for the token request (e.g., { prompt: 'consent' }).
 * @returns {Promise<string>} A promise that resolves with the access token.
 */
function ensureAccessToken(options = { prompt: '' }) {
  if (accessToken) return Promise.resolve(accessToken);

  return new Promise((resolve, reject) => {
    if (!tokenClient) {
      return reject(new Error('Identity client not initialized.'));
    }
    // Define the callback for the token request.
    tokenClient.callback = (tokenResponse) => {
      if (tokenResponse.error) {
        resetSignedInUi();
        return reject(new Error(tokenResponse.error_description || 'Authorization failed.'));
      }
      accessToken = tokenResponse.access_token;
      setSignedInUi();
      resolve(accessToken);
    };
    tokenClient.requestAccessToken(options);
  });
}