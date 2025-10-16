import React from 'react'
import { Box, Button, Card, CardContent, Typography, Alert } from '@mui/material'
import { Refresh as RefreshIcon } from '@mui/icons-material'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true }
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo)
    this.setState({
      error,
      errorInfo
    })

    // Log to external error tracking service
    if (window.trackError) {
      window.trackError(error, errorInfo)
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      return (
        <Box
          display="flex"
          justifyContent="center"
          alignItems="center"
          minHeight="100vh"
          p={3}
          bgcolor="background.default"
        >
          <Card sx={{ maxWidth: 600 }}>
            <CardContent>
              <Alert severity="error" sx={{ mb: 3 }}>
                <Typography variant="h6" gutterBottom>
                  Something went wrong
                </Typography>
                <Typography variant="body2" paragraph>
                  The application encountered an unexpected error. This has been logged
                  and we'll look into it.
                </Typography>
              </Alert>

              <Typography variant="subtitle2" gutterBottom>
                What you can do:
              </Typography>
              <Typography variant="body2" component="ul" sx={{ pl: 2 }}>
                <li>Click "Reload Application" to restart</li>
                <li>Try refreshing your browser</li>
                <li>If the problem persists, contact support</li>
              </Typography>

              <Box mt={3}>
                <Button
                  variant="contained"
                  startIcon={<RefreshIcon />}
                  onClick={this.handleReset}
                  fullWidth
                >
                  Reload Application
                </Button>
              </Box>

              {this.state.error && (
                <Box mt={3}>
                  <Typography variant="caption" color="text.secondary">
                    Technical Details:
                  </Typography>
                  <Box
                    sx={{
                      mt: 1,
                      p: 1.5,
                      bgcolor: 'action.hover',
                      borderRadius: 1,
                      fontFamily: 'monospace',
                      fontSize: '0.75rem',
                      overflowX: 'auto',
                      maxHeight: 200,
                      overflow: 'auto',
                    }}
                  >
                    <Typography variant="caption" component="pre">
                      {this.state.error.toString()}
                      {this.state.errorInfo && '\n\n'}
                      {this.state.errorInfo?.componentStack}
                    </Typography>
                  </Box>
                </Box>
              )}
            </CardContent>
          </Card>
        </Box>
      )
    }

    return this.props.children
  }
}

export default ErrorBoundary
