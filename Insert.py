from PyQt6.QtWidgets import *

sheet = """
QMenuBar {
    background-color: #F8B4B6;
    border: 1px solid gray;
    padding: 5px;
}

QComboBox {
    font-size: 16px
}

QWidget #team_card{
    background-color: #F8B4B6;
    border: 1px solid gray;
    padding: 5px;
    border-radius: 5px
}

QLabel {
    font-size: 18px
}

QLineEdit {
    font-size: 18px
}

QPushButton {
    background-color: #000000;
    color: #ffffff;
    border-radius: 3px;
    padding: 6px;
    font-size: 18px
}
"""


class Insert(QMainWindow):
    def __init__(self, parent):
        try:
            super().__init__()

            self.setStyleSheet(sheet)

            self.parent = parent

            self.setWindowTitle("Add Score")
            self.setGeometry(80, 80, 1000, 60)

            self.mainWidget = QWidget()
            self.mainLayout = QHBoxLayout()
            self.mainLayout.addWidget(QLabel("Team Number:"))
            self.number = QComboBox()

            # Blank out window if teams do not
            self.sortedTeams = sorted(parent.teams, key=lambda x: x.number, reverse=False)
            if len(self.sortedTeams) == 0:
                self.setWindowTitle("No teams added yet!")
            else:
                self.number.addItems([f"{team.number}: {team.name}" for team in self.sortedTeams])
                self.number.setCurrentText(str(self.sortedTeams[0].number) + ": " + self.sortedTeams[0].name)
                self.number.setFixedWidth(400)
                self.number.activated.connect(self.setNextRound)

                self.mainLayout.addWidget(self.number)
                self.mainLayout.addWidget(QLabel("Round:"))

                self.round = QComboBox()
                self.round.setFixedWidth(80)
                self.round.activated.connect(self.updateFormat)
                self.round.addItems(["1", "2", "3"])

                self.score = QLineEdit()
                self.score.setFixedWidth(80)
                self.score.returnPressed.connect(self.insertScore)

                self.add = QPushButton("Add Score")
                self.add.setFixedWidth(160)
                self.add.pressed.connect(self.insertScore)

                self.mainLayout.addWidget(self.round)
                self.mainLayout.addWidget(QLabel("Score:"))
                self.mainLayout.addWidget(self.score)
                self.mainLayout.addWidget(self.add)

                self.mainWidget.setLayout(self.mainLayout)
                self.setCentralWidget(self.mainWidget)

                self.setNextRound()
            self.show()
        except Exception as err:
            raise err

    def setNextRound(self):
        try:
            team = self.parent.fetchTeam(int(self.number.currentText().split(":", -1)[0]))

            if -1 in team.scores:
                # If blank matches remain, then set the current round to the first blank match
                self.round.setCurrentIndex(team.scores.index(-1))
            else:
                # Otherwise, set current round to last match
                self.round.setCurrentIndex(2)

            self.updateFormat()
        except Exception as err:
            print(err)

    def updateFormat(self):
        team = self.parent.fetchTeam(int(self.number.currentText().split(":", -1)[0]))
        num = int(self.round.currentText())

        if team.scores[num - 1] >= 0:
            text = "Override Score"
            color = "#ED1C24"

            # Populate score entry box with existing score
            self.score.setText(str(team.scores[num - 1]))
        else:
            self.score.setText("")
            text = "Add Score"
            color = "#000000"

        self.add.setText(text)
        self.add.setStyleSheet(f"""background-color: {color};
                                color: white;
                                border-radius: 5px;
                                padding: 2px;""")

    def insertScore(self):
        try:
            team = self.parent.fetchTeam(int(self.number.currentText().split(":", -1)[0]))

            if team is not None:
                # Clamp score [-1, 999]
                score = max(-1, min(999, int(self.score.text())))
                team.setScore(int(self.round.currentText()), score)

                self.parent.rerank()
                self.score.setText("")
                self.setNextRound()
        except Exception as err:
            print(err)
