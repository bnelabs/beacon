"""
Baseline model for BNE Engine.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

class BaselineModel:
    """
    A simple baseline model for risk prediction.
    """

    def __init__(self, model_type="logistic_regression"):
        self.model_type = model_type
        self.model = self._create_model()

    def _create_model(self):
        """
        Creates a scikit-learn model based on the model_type.
        """
        if self.model_type == "logistic_regression":
            return LogisticRegression()
        else:
            raise ValueError(f"Unsupported model type: {self.model_type}")

    def train(self, features: pd.DataFrame, target: pd.Series):
        """
        Trains the model on the given data.
        """
        X_train, X_test, y_train, y_test = train_test_split(
            features, target, test_size=0.2, random_state=42
        )
        self.model.fit(X_train, y_train)
        accuracy = self.model.score(X_test, y_test)
        return {"accuracy": accuracy}

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """
        Makes predictions on the given data.
        """
        return self.model.predict(features)

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        """
        Makes probability predictions on the given data.
        """
        return self.model.predict_proba(features)
