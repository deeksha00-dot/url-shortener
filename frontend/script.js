const API_BASE_URL = "http://127.0.0.1:8000";


/* =========================
   HELPER FUNCTIONS
========================= */

function getToken() {
    return localStorage.getItem("token");
}


function redirectToLogin() {
    localStorage.removeItem("token");

    window.location.href = "login.html";
}


function formatDate(dateString) {

    if (!dateString) {
        return "Never";
    }

    const date = new Date(dateString);

    if (isNaN(date.getTime())) {
        return dateString;
    }

    return date.toLocaleString();
}


/* =========================
   LOGIN
========================= */

const loginForm =
    document.getElementById("loginForm");


if (loginForm) {

    // If already logged in, go directly to dashboard
    if (getToken()) {

        window.location.href =
            "dashboard.html";
    }


    loginForm.addEventListener(
        "submit",
        async function (event) {

            event.preventDefault();


            const username =
                document.getElementById(
                    "username"
                ).value.trim();


            const password =
                document.getElementById(
                    "password"
                ).value;


            const message =
                document.getElementById(
                    "loginMessage"
                );


            const loginButton =
                document.getElementById(
                    "loginButton"
                );


            message.textContent = "";

            message.className = "message";


            loginButton.disabled = true;

            loginButton.textContent =
                "Logging in...";


            try {

                const response =
                    await fetch(
                        `${API_BASE_URL}/api/login/`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify({
                                username: username,
                                password: password
                            })
                        }
                    );


                const data =
                    await response.json();


                if (!response.ok) {

                    message.textContent =
                        data.error ||
                        "Invalid username or password.";

                    message.className =
                        "message error-text";

                    return;
                }


                // Save token
                localStorage.setItem(
                    "token",
                    data.token
                );


                // Go to dashboard
                window.location.href =
                    "dashboard.html";

            }


            catch (error) {

                console.error(
                    "Login error:",
                    error
                );


                message.textContent =
                    "Unable to connect to Django server.";

                message.className =
                    "message error-text";

            }


            finally {

                loginButton.disabled = false;

                loginButton.textContent =
                    "Login";
            }

        }
    );

}


/* =========================
   DASHBOARD AUTH CHECK
========================= */

const shortenForm =
    document.getElementById(
        "shortenForm"
    );


if (shortenForm) {

    if (!getToken()) {

        redirectToLogin();

    }

}


/* =========================
   LOGOUT
========================= */

const logoutButton =
    document.getElementById(
        "logoutButton"
    );


if (logoutButton) {

    logoutButton.addEventListener(
        "click",
        function () {

            redirectToLogin();

        }
    );

}


/* =========================
   CREATE SHORT URL
========================= */

if (shortenForm) {

    shortenForm.addEventListener(
        "submit",
        async function (event) {

            event.preventDefault();


            const token =
                getToken();


            if (!token) {

                redirectToLogin();

                return;
            }


            const url =
                document
                    .getElementById("url")
                    .value
                    .trim();


            const customAlias =
                document
                    .getElementById("customAlias")
                    .value
                    .trim();


            const expiresAtInput =
                document
                    .getElementById("expiresAt")
                    .value;


            const message =
                document.getElementById(
                    "shortenMessage"
                );


            const shortenButton =
                document.getElementById(
                    "shortenButton"
                );


            const resultBox =
                document.getElementById(
                    "shortUrlResult"
                );


            const shortUrlLink =
                document.getElementById(
                    "shortUrlLink"
                );


            message.textContent = "";

            message.className =
                "message";


            const payload = {
                url: url
            };


            // Custom alias
            if (customAlias) {

                payload.custom_alias =
                    customAlias;

            }


            // Expiration
            if (expiresAtInput) {

                const expirationDate =
                    new Date(
                        expiresAtInput
                    );


                if (
                    isNaN(
                        expirationDate.getTime()
                    )
                ) {

                    message.textContent =
                        "Invalid expiration date.";

                    message.className =
                        "message error-text";

                    return;
                }


                payload.expires_at =
                    expirationDate.toISOString();

            }


            shortenButton.disabled = true;

            shortenButton.textContent =
                "Creating...";


            try {

                const response =
                    await fetch(
                        `${API_BASE_URL}/api/shorten/`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json",

                                "Authorization":
                                    `Token ${token}`
                            },

                            body: JSON.stringify(
                                payload
                            )
                        }
                    );


                const data =
                    await response.json();


                // Token expired/invalid
                if (
                    response.status === 401
                ) {

                    redirectToLogin();

                    return;
                }


                if (!response.ok) {

                    let errorMessage =
                        "Unable to create short URL.";


                    if (data.error) {

                        errorMessage =
                            data.error;

                    }
                    else if (data.url) {

                        errorMessage =
                            Array.isArray(data.url)
                                ? data.url.join(", ")
                                : data.url;

                    }
                    else if (data.custom_alias) {

                        errorMessage =
                            Array.isArray(
                                data.custom_alias
                            )
                                ? data.custom_alias.join(
                                    ", "
                                )
                                : data.custom_alias;

                    }


                    message.textContent =
                        errorMessage;

                    message.className =
                        "message error-text";


                    return;
                }


                // Display successful result
                shortUrlLink.textContent =
                    data.short_url;


                shortUrlLink.href =
                    data.short_url;


                resultBox.classList.remove(
                    "hidden"
                );


                message.textContent =
                    "URL created successfully.";

                message.className =
                    "message success-text";


                // Clear form
                shortenForm.reset();


                // Refresh URL list
                loadMyUrls();

            }


            catch (error) {

                console.error(
                    "Shorten error:",
                    error
                );


                message.textContent =
                    "Unable to connect to Django server.";

                message.className =
                    "message error-text";
            }


            finally {

                shortenButton.disabled =
                    false;

                shortenButton.textContent =
                    "Create Short URL";
            }

        }
    );

}


/* =========================
   COPY BUTTON
========================= */

const copyButton =
    document.getElementById(
        "copyButton"
    );


if (copyButton) {

    copyButton.addEventListener(
        "click",
        async function () {

            const shortUrl =
                document.getElementById(
                    "shortUrlLink"
                ).textContent;


            const copyMessage =
                document.getElementById(
                    "copyMessage"
                );


            try {

                await navigator.clipboard.writeText(
                    shortUrl
                );


                copyButton.textContent =
                    "Copied!";


                copyMessage.textContent =
                    "Short URL copied to clipboard.";


                setTimeout(
                    function () {

                        copyButton.textContent =
                            "Copy";

                        copyMessage.textContent =
                            "";

                    },
                    2000
                );

            }


            catch (error) {

                console.error(
                    "Copy error:",
                    error
                );


                copyMessage.textContent =
                    "Unable to copy URL.";
            }

        }
    );

}


/* =========================
   LOAD MY URLS
========================= */

async function loadMyUrls() {

    const container =
        document.getElementById(
            "urlsContainer"
        );


    if (!container) {
        return;
    }


    const token =
        getToken();


    if (!token) {

        redirectToLogin();

        return;
    }


    container.innerHTML = `
        <div class="loading">
            Loading your URLs...
        </div>
    `;


    try {

        const response =
            await fetch(
                `${API_BASE_URL}/api/my-urls/`,
                {
                    method: "GET",

                    headers: {
                        "Authorization":
                            `Token ${token}`
                    }
                }
            );


        // Invalid token
        if (
            response.status === 401
        ) {

            redirectToLogin();

            return;
        }


        if (!response.ok) {

            container.innerHTML = `
                <div class="empty-state">
                    Unable to load your URLs.
                </div>
            `;

            return;
        }


        const urls =
            await response.json();


        // No URLs
        if (
            !Array.isArray(urls) ||
            urls.length === 0
        ) {

            container.innerHTML = `
                <div class="empty-state">
                    You have not created any short URLs yet.
                </div>
            `;

            return;
        }


        container.innerHTML = "";


        urls.forEach(
            function (url) {

                const card =
                    document.createElement(
                        "div"
                    );


                card.className =
                    "url-card";


                // Top section
                const top =
                    document.createElement(
                        "div"
                    );


                top.className =
                    "url-card-top";


                const codeSection =
                    document.createElement(
                        "div"
                    );


                const code =
                    document.createElement(
                        "div"
                    );


                code.className =
                    "url-code";


                code.textContent =
                    url.code;


                const shortLink =
                    document.createElement(
                        "a"
                    );


                shortLink.className =
                    "short-link";


                shortLink.href =
                    `${API_BASE_URL}/${encodeURIComponent(url.code)}/`;


                shortLink.target =
                    "_blank";


                shortLink.textContent =
                    shortLink.href;


                codeSection.appendChild(
                    code
                );


                codeSection.appendChild(
                    shortLink
                );


                const deleteButton =
                    document.createElement(
                        "button"
                    );


                deleteButton.className =
                    "delete-btn";


                deleteButton.textContent =
                    "Delete";


                deleteButton.addEventListener(
                    "click",
                    function () {

                        deleteUrl(
                            url.code
                        );

                    }
                );


                top.appendChild(
                    codeSection
                );


                top.appendChild(
                    deleteButton
                );


                // Original URL
                const original =
                    document.createElement(
                        "p"
                    );


                original.className =
                    "original-url";


                original.textContent =
                    url.original_url;


                // Statistics
                const stats =
                    document.createElement(
                        "div"
                    );


                stats.className =
                    "url-stats";


                // Clicks
                stats.appendChild(
                    createStat(
                        "Clicks",
                        url.click_count
                    )
                );


                // Created
                stats.appendChild(
                    createStat(
                        "Created",
                        formatDate(
                            url.created_at
                        )
                    )
                );


                // Expiration
                stats.appendChild(
                    createStat(
                        "Expires",
                        formatDate(
                            url.expires_at
                        )
                    )
                );


                card.appendChild(
                    top
                );


                card.appendChild(
                    original
                );


                card.appendChild(
                    stats
                );


                container.appendChild(
                    card
                );

            }
        );

    }


    catch (error) {

        console.error(
            "Load URLs error:",
            error
        );


        container.innerHTML = `
            <div class="empty-state">
                Unable to connect to Django server.
            </div>
        `;

    }

}


/* =========================
   CREATE STAT
========================= */

function createStat(
    label,
    value
) {

    const stat =
        document.createElement(
            "div"
        );


    stat.className =
        "stat";


    const statLabel =
        document.createElement(
            "span"
        );


    statLabel.className =
        "stat-label";


    statLabel.textContent =
        label;


    const statValue =
        document.createElement(
            "span"
        );


    statValue.className =
        "stat-value";


    statValue.textContent =
        value;


    stat.appendChild(
        statLabel
    );


    stat.appendChild(
        statValue
    );


    return stat;
}


/* =========================
   DELETE URL
========================= */

async function deleteUrl(code) {

    const token =
        getToken();


    if (!token) {

        redirectToLogin();

        return;
    }


    const confirmed =
        window.confirm(
            `Are you sure you want to delete "${code}"?`
        );


    if (!confirmed) {
        return;
    }


    try {

        const response =
            await fetch(
                `${API_BASE_URL}/api/urls/${encodeURIComponent(code)}/delete/`,
                {
                    method: "DELETE",

                    headers: {
                        "Authorization":
                            `Token ${token}`
                    }
                }
            );


        if (
            response.status === 401
        ) {

            redirectToLogin();

            return;
        }


        if (
            response.status === 204
        ) {

            await loadMyUrls();

            return;
        }


        let data = {};

        try {

            data =
                await response.json();

        }
        catch (error) {

            // Response may have no JSON body

        }


        alert(
            data.error ||
            "Unable to delete URL."
        );

    }


    catch (error) {

        console.error(
            "Delete error:",
            error
        );


        alert(
            "Unable to connect to Django server."
        );
    }

}


/* =========================
   REFRESH BUTTON
========================= */

const refreshButton =
    document.getElementById(
        "refreshButton"
    );


if (refreshButton) {

    refreshButton.addEventListener(
        "click",
        function () {

            loadMyUrls();

        }
    );

}


/* =========================
   INITIAL DASHBOARD LOAD
========================= */

if (shortenForm) {

    loadMyUrls();

}