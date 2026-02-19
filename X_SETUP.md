# X Integration Guide

Your Fantastic Claw agent is now integrated with X! Here's how to set it up.

## Step 1: Create an X Bot Account

1. Go to [x.com](https://x.com) and create a new account
2. Name it something like `@FantasticClaw` or `@TheClaw`
3. Set an avatar and bio

## Step 2: Apply for X API Access

1. Go to [developer.x.com](https://developer.x.com/en/portal/dashboard)
2. Sign in with your bot account
3. Click **"Create an app"** or go to **Dashboard → Projects & Apps**
4. Fill in the app details:
   - **App name**: The Fantastic Claw
   - **Use case**: Bot for product analysis
   - **Description**: An AI agent that analyzes product listings for flipping potential

5. Accept terms and create the app

## Step 3: Get Your API Credentials

1. Go to your app's **Keys and tokens** page
2. Copy these credentials:
   - **API Key** (Consumer Key)
   - **API Secret** (Consumer Secret)
   - **Bearer Token**
   - **Access Token**
   - **Access Token Secret**

3. Add them to your `.env` file:

```
X_CONSUMER_KEY=your_consumer_key
X_CONSUMER_SECRET=your_consumer_secret
X_ACCESS_TOKEN=your_access_token
X_ACCESS_TOKEN_SECRET=your_access_token_secret
X_BEARER_TOKEN=your_bearer_token
BOT_X_HANDLE=YourBotHandle
```

## Step 4: Enable v2 API and Restricted Endpoints

1. In **Keys and tokens → Settings** (scroll down)
2. Change **API access level** to: **Elevated**
3. Enable these **OAuth 2.0 Settings**:
   - Read write - Allow your app to make POST requests
   - Post.read scope - Allow reading posts
   - Users.read scope - Allow reading users info

## Step 5: Set Up the Webhook

Your Render deployment URL is where X will send mentions.

1. Go to **Keys and tokens → Webhooks and connections**
2. Click **Add webhook**
3. Enter your webhook URL:
   ```
   https://your-render-app-name.onrender.com/x-webhook
   ```

4. X will send a verification request - your app will auto-respond with the correct token

5. In **Environments → Dev environment**, select your webhook

## Step 6: Subscribe to User Events

1. In **Webhooks and connections**, go to **Account Activity API**
2. Click **Subscribe** to receive mentions

## Step 7: Test It!

Now when someone posts and mentions your bot, it will respond:

```
@FantasticClaw https://www.example.com/vintage-chair

# Bot responds with:
@User This vintage chair at $45 is 40% below market value. Great flip! 🦀
```

## How It Works

1. **User post**: `@FantasticClaw https://example.com/product`
2. **X sends**: POST request to `/x-webhook`
3. **Your agent**:
   - Extracts the URL
   - Scrapes the product
   - Analyzes with GPT-4o
   - Replies with analysis
4. **Bot posts back**: Witty evaluation of the deal

## Endpoints

### Manual Trigger
```bash
POST /trigger-claw?url=https://example.com/product
```

### Health Check
```bash
GET /
```

### X Webhook (Automatic)
```
POST /x-webhook
GET /x-webhook?crc_token=...
```

## Troubleshooting

### Bot not receiving mentions
- ✓ Check webhook URL is correct and publicly accessible
- ✓ Verify API credentials in `.env`
- ✓ Make sure you're using **Elevated** API access level
- ✓ Check Render logs: `Render dashboard → Logs`

### Webhook verification failing
- Render needs to respond within 3 seconds
- Check that your app is running and responding to GET `/x-webhook`

### Rate limiting
- X has rate limits (450 posts/15 minutes)
- The code includes `wait_on_rate_limit=True` to handle this

### Check Logs
```bash
# On Render dashboard, view real-time logs
Render → Your App → Logs
```

Look for messages like:
```
New mention: @FantasticClaw https://example.com/product
Replied to post 1234567890
```

## Advanced: Custom Analysis

To change how the bot analyzes products, edit the system prompt in `agent.py`:

```python
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are The Fantastic Claw. [Your custom instructions here]"),
    ...
])
```

## API Limits

- **Post read**: 450 posts/15 minutes
- **Post creation**: 300 posts/15 minutes
- **User lookup**: 15 requests/15 minutes

The code automatically handles rate limiting with `wait_on_rate_limit=True`.

## Security Notes

- ✅ **Never commit `.env`** - it's in `.gitignore`
- ✅ **Keep API keys private** - never share them
- ✅ **Rotate tokens regularly** in X dashboard
- ✅ **Monitor usage** - Watch your API call count

## Next Steps

1. Add your X API credentials to `.env`
2. Restart your Render app
3. Post and mention your bot with a product link
4. Watch it respond! 🦀

## Support

For issues:
- Check X API status: [status.x.com](https://status.x.com)
- View Render logs: Your app dashboard
- X API docs: [developer.x.com/en/docs](https://developer.x.com/en/docs/twitter-api)

## Resources

- **X Developer Portal**: [developer.x.com](https://developer.x.com)
- **X Status Page**: [status.x.com](https://status.x.com)
- **API Documentation**: [developer.x.com/en/docs/twitter-api](https://developer.x.com/en/docs/twitter-api)
- **Render Deployment**: [render.com](https://render.com)
