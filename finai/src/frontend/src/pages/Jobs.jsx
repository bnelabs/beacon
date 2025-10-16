import { Typography, Box } from '@mui/material'

export default function Jobs() {
  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Background Jobs
      </Typography>
      <Typography variant="body1" color="text.secondary">
        View and manage background tasks like data collection, model training, and predictions.
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
        (Full implementation coming soon - will include job list, progress tracking, and job controls)
      </Typography>
    </Box>
  )
}
