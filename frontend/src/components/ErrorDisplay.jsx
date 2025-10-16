import { useState } from 'react'
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Collapse,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Typography,
  IconButton,
} from '@mui/material'
import {
  Error as ErrorIcon,
  Warning as WarningIcon,
  Info as InfoIcon,
  CheckCircle as SuccessIcon,
  ExpandMore as ExpandIcon,
  ExpandLess as CollapseIcon,
  Refresh as RetryIcon,
  ContentCopy as CopyIcon,
  LightbulbOutlined as SolutionIcon,
} from '@mui/icons-material'

export default function ErrorDisplay({ error, onRetry, onDismiss }) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  if (!error) return null

  // Parse error from API
  const errorData = typeof error === 'string'
    ? { user_message: error, severity: 'error' }
    : error.response?.data?.detail || error

  const {
    severity = 'error',
    category,
    user_message,
    technical_message,
    solutions = [],
    retry_recommended = false,
    contact_support = false,
  } = errorData

  const getSeverityIcon = () => {
    switch (severity) {
      case 'critical':
      case 'error':
        return <ErrorIcon />
      case 'warning':
        return <WarningIcon />
      case 'info':
        return <InfoIcon />
      default:
        return <ErrorIcon />
    }
  }

  const getSeverityColor = () => {
    switch (severity) {
      case 'critical':
      case 'error':
        return 'error'
      case 'warning':
        return 'warning'
      case 'info':
        return 'info'
      default:
        return 'error'
    }
  }

  const handleCopyTechnical = () => {
    if (technical_message) {
      navigator.clipboard.writeText(technical_message)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <Alert
      severity={getSeverityColor()}
      icon={getSeverityIcon()}
      action={
        <Box>
          {retry_recommended && onRetry && (
            <Button
              color="inherit"
              size="small"
              startIcon={<RetryIcon />}
              onClick={onRetry}
              sx={{ mr: 1 }}
            >
              Retry
            </Button>
          )}
          {onDismiss && (
            <Button color="inherit" size="small" onClick={onDismiss}>
              Dismiss
            </Button>
          )}
        </Box>
      }
      sx={{ mb: 2 }}
    >
      <AlertTitle>
        <Box display="flex" alignItems="center" justifyContent="space-between">
          <span>{user_message || 'An error occurred'}</span>
          {(solutions.length > 0 || technical_message) && (
            <IconButton
              size="small"
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? <CollapseIcon /> : <ExpandIcon />}
            </IconButton>
          )}
        </Box>
      </AlertTitle>

      {category && (
        <Typography variant="caption" display="block" sx={{ mb: 1 }}>
          Category: {category}
        </Typography>
      )}

      <Collapse in={expanded}>
        {/* Solutions */}
        {solutions.length > 0 && (
          <Box sx={{ mt: 2 }}>
            <Box display="flex" alignItems="center" gap={1} mb={1}>
              <SolutionIcon fontSize="small" />
              <Typography variant="subtitle2" fontWeight="bold">
                Possible Solutions:
              </Typography>
            </Box>
            <List dense>
              {solutions.map((solution, idx) => (
                <ListItem key={idx}>
                  <ListItemIcon sx={{ minWidth: 32 }}>
                    <Typography variant="body2" color="text.secondary">
                      {idx + 1}.
                    </Typography>
                  </ListItemIcon>
                  <ListItemText
                    primary={solution}
                    primaryTypographyProps={{ variant: 'body2' }}
                  />
                </ListItem>
              ))}
            </List>
          </Box>
        )}

        {/* Contact Support */}
        {contact_support && (
          <Alert severity="info" sx={{ mt: 2 }}>
            If these solutions don't work, please contact your system administrator
            with the technical details below.
          </Alert>
        )}

        {/* Technical Details */}
        {technical_message && (
          <Box sx={{ mt: 2 }}>
            <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
              <Typography variant="subtitle2" fontWeight="bold">
                Technical Details:
              </Typography>
              <Button
                size="small"
                startIcon={<CopyIcon />}
                onClick={handleCopyTechnical}
              >
                {copied ? 'Copied!' : 'Copy'}
              </Button>
            </Box>
            <Box
              sx={{
                bgcolor: 'action.hover',
                p: 1.5,
                borderRadius: 1,
                fontFamily: 'monospace',
                fontSize: '0.75rem',
                overflowX: 'auto',
              }}
            >
              {technical_message}
            </Box>
          </Box>
        )}
      </Collapse>
    </Alert>
  )
}
